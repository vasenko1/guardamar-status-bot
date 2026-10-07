import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegrambot._transport import BoundedFetchError
from telegrambot.supermarket_hours import (
    DIA_DETAIL_URL, MERCADONA_LOCATOR_URL, MASYMAS_LOCATOR_URL,
    StoreDayStatus, StoreScheduleObservation, SupermarketSourceError,
    _allow_dia, _allow_masymas, _allow_mercadona_data, _allow_mercadona_locator,
    _fetch, _fetch_masymas_sync, parse_mercadona_data, parse_dia_detail, parse_masymas_locator,
)
from telegrambot.supermarket_closures import (
    SupermarketState, SupermarketDeliveryUncertain,
    _empty_state, _prune_delivery_state,
    collect_observations, plan_batch, monitor_supermarkets,
)

TZ=ZoneInfo('Europe/Madrid')
def at(day,hour=8): return datetime(day.year,day.month,day.day,hour,15,tzinfo=TZ)

class SourceTests(unittest.TestCase):
    def test_mercadona_real_contract_7_9_12_and_routine_sunday(self):
        root={
          'fechaCreacion':'07-10-2026',
          'tiendasFull':[{
            'id':283185312286,'cp':'03140','lc':'Guardamar del Segura','dr':'CL MEDITERRÁNEO, 14',
            'in':'C#0900#C#0900#C#C#0900','fi':'C#2130#C#2130#C#C#2130',
            'fs':'09/10/26-C#11/10/26-C#12/10/26-C#18/10/26-C#25/10/26-C'
          }]
        }
        obs=parse_mercadona_data(('var dataJson='+json.dumps(root)+';').encode(),at(date(2026,10,7)))
        self.assertIn(date(2026,10,7),obs.closures)
        self.assertIn(date(2026,10,9),obs.closures)
        self.assertIn(date(2026,10,12),obs.closures)
        self.assertNotIn(date(2026,10,11),obs.closures)
        self.assertTrue(obs.status_on(date(2026,10,8)).is_open)

    def test_mercadona_stale_dataset_fails_closed(self):
        root={'fechaCreacion':'06-10-2026','tiendasFull':[]}
        with self.assertRaisesRegex(Exception,'stale'):
            parse_mercadona_data(('var dataJson='+json.dumps(root)).encode(),at(date(2026,10,7)))

    def test_dia_real_contract_distinguishes_closed_and_shortened_open(self):
        payload=json.dumps({
          'tiendaCodigo':36111,'codigoPostal':'03140','localidad':'Guardamar del Segura','direccion':'CL LA REDONDA 40',
          'horariosTienda':{str(i):'09:00 - 21:30' for i in range(1,7)},
          'festivosTienda':['2026-10-07','2026-10-09','2026-10-12','2026-11-29'],
          'horariosAperturaFestivo':['','','09:00 - 21:30','09:30 - 15:00'],
          'inicioCierreTemp':None,'finCierreTemp':None,'fechaApertura':None,
        }).encode()
        obs=parse_dia_detail(payload,at(date(2026,10,7)))
        self.assertEqual(obs.closures,{date(2026,10,7),date(2026,10,9)})
        self.assertIn(date(2026,10,12),obs.explicit_open_days)
        self.assertIn(date(2026,11,29),obs.explicit_open_days)

    def test_dia_single_sunday_difference_is_not_automated(self):
        payload=json.dumps({
          'tiendaCodigo':36111,'codigoPostal':'03140','localidad':'Guardamar del Segura','direccion':'CL LA REDONDA 40',
          'horariosTienda':{**{str(i):'09:00 - 21:30' for i in range(1,7)},'7':'09:30 - 15:00'},
          'festivosTienda':['2026-10-11'],
          'horariosAperturaFestivo':[''],
          'inicioCierreTemp':None,'finCierreTemp':None,
        }).encode()
        obs=parse_dia_detail(payload,at(date(2026,10,7)))
        self.assertNotIn(date(2026,10,11),obs.closures)
        self.assertEqual(obs.regular_open_weekdays,frozenset(range(6)))

    def test_exact_url_policies_fail_closed_on_drift(self):
        self.assertTrue(_allow_mercadona_locator(MERCADONA_LOCATOR_URL))
        self.assertFalse(_allow_mercadona_locator(MERCADONA_LOCATOR_URL+'?x=1'))
        self.assertTrue(_allow_mercadona_data(
            'https://storage.googleapis.com/pro-bucket-wcorp-files/json/data.js?timestamp=123'
        ))
        self.assertFalse(_allow_mercadona_data(
            'https://storage.googleapis.com/pro-bucket-wcorp-files/json/data.js?timestamp=123&x=1'
        ))
        self.assertTrue(_allow_dia(DIA_DETAIL_URL))
        self.assertFalse(_allow_dia(DIA_DETAIL_URL+'&x=1'))
        self.assertTrue(_allow_masymas(MASYMAS_LOCATOR_URL))
        self.assertFalse(_allow_masymas('https://masymas.com/localizadordetiendas/localizador.php'))

    def test_navigation_fallback_is_one_bounded_retry(self):
        error=BoundedFetchError('blocked',code='HTTP',status=403)
        with patch(
            'telegrambot.supermarket_hours.fetch_bounded',
            side_effect=[error,(b'ok',MASYMAS_LOCATOR_URL,'text/html')],
        ) as fetch:
            payload=_fetch(
                MASYMAS_LOCATOR_URL,
                policy=_allow_masymas,
                limit=1024,
                types=frozenset({'text/html'}),
                accept='text/html',
                method='POST',
                data=b'x=1',
                navigation_fallback=True,
            )
        self.assertEqual(payload,b'ok')
        self.assertEqual(fetch.call_count,2)

    def test_masymas_runtime_posts_official_locality_value(self):
        html='''<table><tr><td>ALICANTE</td><td>GUARDAMAR DEL SEGURA</td><td>AVDA. PUERTO, 18 Y 20</td><td>Lun-Sab 9:00-21:30. Cierra el 09/10/2026.</td></tr></table>'''
        with patch('telegrambot.supermarket_hours._fetch', return_value=html.encode()) as fetch:
            obs=_fetch_masymas_sync(at(date(2026,10,8)))
        kwargs=fetch.call_args.kwargs
        self.assertEqual(
            kwargs['data'].decode(),
            'IdProvincia=ALICANTE&IdLocalidad=GUARDAMAR+DEL+SEGURA&enviado=+Buscar+',
        )
        self.assertIn(date(2026,10,9),obs.closures)

    def test_masymas_nested_legacy_table_keeps_store_row_independent(self):
        html='''<table>
          <tr><td>
            <form><select><option>GUARDAMAR DEL SEGURA</option></select></form>
            <table>
              <tr class="gris">
                <td>ALICANTE</td>
                <td>GUARDAMAR DEL SEGURA</td>
                <td>AVDA. PUERTO, 18 Y 20</td>
                <td>Lun-Sab 9:00-21:30. Cierra el 09/10/2026. Abre el 12/10/2026 9:00-14:30</td>
              </tr>
            </table>
          </td></tr>
        </table>'''
        obs=parse_masymas_locator(html.encode(),at(date(2026,10,8)))
        self.assertIn(date(2026,10,9),obs.closures)
        self.assertTrue(obs.status_on(date(2026,10,12)).is_open)
        self.assertEqual(obs.status_on(date(2026,10,12)).intervals,('09:00–14:30',))

    def test_masymas_real_contract(self):
        html='''<table><tr><td>ALICANTE</td><td>GUARDAMAR DEL SEGURA</td><td>AVDA. PUERTO, 18 Y 20</td><td>Lun-Sab 9:00-21:30. Cierra el 07/10/2026. Cierra el 09/10/2026. Abre el 12/10/2026 9:00-14:30</td></tr></table>'''
        obs=parse_masymas_locator(html.encode(),at(date(2026,10,7)))
        self.assertEqual(obs.closures,{date(2026,10,7),date(2026,10,9)})
        self.assertTrue(obs.status_on(date(2026,10,12)).is_open)
        self.assertEqual(obs.status_on(date(2026,10,12)).intervals,('09:00–14:30',))

class LifecycleTests(unittest.TestCase):
    def obs(self,key,day_statuses):
        from telegrambot.supermarket_hours import STORE_NAMES,STORE_ADDRESSES
        return StoreScheduleObservation(key,STORE_NAMES[key],STORE_ADDRESSES[key],at(date(2026,10,7)),frozenset(range(6)),tuple(day_statuses))

    def test_october_9_groups_all_three_and_is_human(self):
        target=date(2026,10,9)
        observations=tuple(self.obs(k,[StoreDayStatus(target,False)]) for k in ('mercadona_guardamar','masymas_guardamar','dia_guardamar'))
        plan=plan_batch({'version':1,'stores':{},'sent':[],'uncertain_batch':None,'last_delivery_day':None},observations,at(date(2026,10,8)))
        self.assertIsNotNone(plan)
        self.assertIn('Завтра, 9 октября',plan.message)
        self.assertIn('Mercadona, masymas и DIA не работают',plan.message)
        self.assertIn('все три магазина закрыты на весь день',plan.message)
        self.assertIn('официальный выходной — День Валенсийского сообщества',plan.message)
        self.assertEqual(len(plan.groups),1)

    def test_october_12_mercadona_closed_but_other_two_explicitly_open(self):
        target=date(2026,10,12)
        observations=(
          self.obs('mercadona_guardamar',[StoreDayStatus(target,False)]),
          self.obs('masymas_guardamar',[StoreDayStatus(target,True,('09:00–14:30',))]),
          self.obs('dia_guardamar',[StoreDayStatus(target,True,('09:00–21:30',))]),
        )
        plan=plan_batch({'version':1,'stores':{},'sent':[],'uncertain_batch':None,'last_delivery_day':None},observations,at(date(2026,10,7)))
        # Wednesday discovery, >=2 days away in current week? Oct 12 is next Monday, so not early yet.
        self.assertIsNone(plan)
        plan=plan_batch({'version':1,'stores':{},'sent':[],'uncertain_batch':None,'last_delivery_day':None},observations,at(date(2026,10,12)))
        self.assertIn('Mercadona не работает',plan.message)
        self.assertIn('masymas и DIA работают',plan.message)
        self.assertNotIn('14:30',plan.message)

    def test_monday_tuesday_closure_collapses_early_and_tomorrow(self):
        monday=date(2026,10,19); tuesday=date(2026,10,20)
        obs=self.obs('mercadona_guardamar',[StoreDayStatus(tuesday,False)])
        obs=StoreScheduleObservation(obs.store_key,obs.store_name,obs.address,at(monday),obs.regular_open_weekdays,obs.days)
        plan=plan_batch({'version':1,'stores':{},'sent':[],'uncertain_batch':None,'last_delivery_day':None},[obs],at(monday))
        self.assertEqual(set(plan.keys),{
          'early:2026-10-20:mercadona_guardamar','tomorrow:2026-10-20:mercadona_guardamar'})
        self.assertIn('Завтра, 20 октября',plan.message)

    def test_routine_sunday_closure_is_silent(self):
        sunday=date(2026,10,11)
        obs=self.obs('mercadona_guardamar',[StoreDayStatus(sunday,False)])
        self.assertIsNone(plan_batch({'version':1,'stores':{},'sent':[],'uncertain_batch':None,'last_delivery_day':None},[obs],at(date(2026,10,10))))

    def test_late_discovered_friday_gets_one_early_phase(self):
        wed=date(2026,10,7); fri=date(2026,10,9)
        obs=self.obs('mercadona_guardamar',[StoreDayStatus(fri,False)])
        plan=plan_batch({'version':1,'stores':{},'sent':[],'uncertain_batch':None,'last_delivery_day':None},[obs],at(wed))
        self.assertEqual(plan.keys,('early:2026-10-09:mercadona_guardamar',))

    def test_known_after_monday_does_not_fabricate_late_early(self):
        wed=date(2026,10,7); fri=date(2026,10,9)
        obs=self.obs('mercadona_guardamar',[StoreDayStatus(fri,False)])
        state={'version':1,'stores':{'mercadona_guardamar':{'observed_at':at(date(2026,10,6)).isoformat(),'closures':['2026-10-09']}},'sent':[],'uncertain_batch':None,'last_delivery_day':None}
        self.assertIsNone(plan_batch(state,[obs],at(wed)))

    def test_nonholiday_exception_explains_that_the_store_normally_works(self):
        now = at(date(2026, 10, 8))
        target = date(2026, 10, 10)
        obs = self.obs("mercadona_guardamar", [StoreDayStatus(target, False)])
        obs = StoreScheduleObservation(
            obs.store_key, obs.store_name, obs.address, now, obs.regular_open_weekdays, obs.days
        )
        plan = plan_batch(
            {"version": 1, "stores": {}, "sent": [], "confirmed": [], "uncertain_batch": None, "last_delivery_day": None},
            (obs,),
            now,
        )
        self.assertIsNotNone(plan)
        self.assertIn("По обычному графику в этот день магазин работает.", plan.message)
        self.assertNotIn("официальный выходной", plan.message)

    def test_verified_open_corrects_previous_future_claim(self):
        target=date(2026,10,9)
        obs=self.obs('mercadona_guardamar',[StoreDayStatus(target,True,('09:00–21:30',))])
        state={'version':1,'stores':{},'sent':['early:2026-10-09:mercadona_guardamar'],'confirmed':['early:2026-10-09:mercadona_guardamar'],'uncertain_batch':None,'last_delivery_day':None}
        plan=plan_batch(state,[obs],at(date(2026,10,8)))
        self.assertEqual(plan.keys,('correction:2026-10-09:mercadona_guardamar',))
        self.assertIn('Завтра, 9 октября, <b>Mercadona работает</b>',plan.message)
        self.assertIn('Ранее мы писали',plan.message)
        self.assertNotIn('на в',plan.message)


    def test_ambiguous_prior_claim_does_not_trigger_correction(self):
        target=date(2026,10,9)
        key='early:2026-10-09:mercadona_guardamar'
        obs=self.obs('mercadona_guardamar',[StoreDayStatus(target,True,('09:00–21:30',))])
        state={
            'version':1,'stores':{},'sent':[key],'confirmed':[],
            'uncertain_batch':{'local_day':'2026-10-07','keys':[key]},
            'last_delivery_day':None,
        }
        self.assertIsNone(plan_batch(state,[obs],at(date(2026,10,8))))

    def test_correction_today_sorts_before_later_week_closure(self):
        today=date(2026,10,7); later=date(2026,10,9)
        observations=[
          self.obs('mercadona_guardamar',[StoreDayStatus(today,True)]),
          self.obs('dia_guardamar',[StoreDayStatus(later,False)]),
        ]
        state={'version':1,'stores':{},'sent':['tomorrow:2026-10-07:mercadona_guardamar'],'confirmed':['tomorrow:2026-10-07:mercadona_guardamar'],'uncertain_batch':None,'last_delivery_day':None}
        plan=plan_batch(state,observations,at(today))
        self.assertEqual(plan.groups[0].kind,'correction')
        self.assertEqual(plan.groups[0].target_date,today)

class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def observation(self):
        return StoreScheduleObservation('mercadona_guardamar','Mercadona','addr',at(date(2026,10,8)),frozenset(range(6)),(StoreDayStatus(date(2026,10,9),False),))

    async def test_success_is_at_most_once_same_day(self):
        with tempfile.TemporaryDirectory() as d:
            state=SupermarketState(Path(d)/'state.json'); calls=[]
            async def send(msg): calls.append(msg); return 10
            self.assertEqual(await monitor_supermarkets(state,at(date(2026,10,8)),[self.observation()],send),'published')
            self.assertEqual(await monitor_supermarkets(state,at(date(2026,10,8)),[self.observation()],send),'no_notice')
            self.assertEqual(len(calls),1)

    async def test_ambiguous_reserves_keys_and_blocks_same_day_resend(self):
        with tempfile.TemporaryDirectory() as d:
            state=SupermarketState(Path(d)/'state.json')
            async def uncertain(msg): raise SupermarketDeliveryUncertain()
            with self.assertRaises(SupermarketDeliveryUncertain):
                await monitor_supermarkets(state,at(date(2026,10,8)),[self.observation()],uncertain)
            calls=[]
            async def send(msg): calls.append(msg); return 10
            self.assertEqual(await monitor_supermarkets(state,at(date(2026,10,8)),[self.observation()],send),'no_notice')
            self.assertEqual(calls,[])
            raw=state.read(); self.assertIsNotNone(raw['uncertain_batch']); self.assertIn('tomorrow:2026-10-09:mercadona_guardamar',raw['sent'])

    async def test_deterministic_failure_rolls_back_reservation(self):
        with tempfile.TemporaryDirectory() as d:
            state=SupermarketState(Path(d)/'state.json')
            async def fail(msg): raise RuntimeError('no')
            with self.assertRaises(RuntimeError):
                await monitor_supermarkets(state,at(date(2026,10,8)),[self.observation()],fail)
            self.assertNotIn('tomorrow:2026-10-09:mercadona_guardamar',state.read()['sent'])
            calls=[]
            async def send(msg): calls.append(msg); return 1
            self.assertEqual(await monitor_supermarkets(state,at(date(2026,10,8)),[self.observation()],send),'published')
            self.assertEqual(len(calls),1)


    async def test_late_discovery_deterministic_failure_retries_as_early(self):
        with tempfile.TemporaryDirectory() as d:
            state=SupermarketState(Path(d)/'state.json')
            now=at(date(2026,10,7))
            obs=StoreScheduleObservation(
                'mercadona_guardamar','Mercadona','addr',now,frozenset(range(6)),
                (StoreDayStatus(date(2026,10,9),False),),
            )
            async def fail(msg): raise RuntimeError('no')
            with self.assertRaises(RuntimeError):
                await monitor_supermarkets(state,now,[obs],fail)
            self.assertEqual(state.read()['stores'],{})
            calls=[]
            async def send(msg): calls.append(msg); return 1
            self.assertEqual(await monitor_supermarkets(state,now,[obs],send),'published')
            self.assertEqual(len(calls),1)
            self.assertIn('В пятницу, 9 октября',calls[0])
            self.assertIn('early:2026-10-09:mercadona_guardamar',state.read()['confirmed'])



class StatePruningTests(unittest.TestCase):
    def test_pruning_preserves_uncertain_key_and_confirmed_subset(self):
        today=date(2026,10,7)
        uncertain='early:2025-01-01:mercadona_guardamar'
        value=_empty_state()
        value['sent']=[uncertain]
        for offset in range(90):
            target=today-timedelta(days=offset)
            for store in ('mercadona_guardamar','masymas_guardamar','dia_guardamar'):
                value['sent'].append(f'early:{target.isoformat()}:{store}')
        value['confirmed']=list(value['sent'][-30:])
        value['uncertain_batch']={'local_day':'2025-01-01','keys':[uncertain]}
        _prune_delivery_state(value,today)
        self.assertIn(uncertain,value['sent'])
        self.assertLessEqual(len(value['sent']),256)
        self.assertTrue(set(value['confirmed']).issubset(value['sent']))



class CollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_retailer_failure_does_not_suppress_others(self):
        now=at(date(2026,10,8))
        good=StoreScheduleObservation(
            'dia_guardamar','DIA','addr',now,frozenset(range(6)),
            (StoreDayStatus(date(2026,10,9),False),),
        )
        async def broken(_now):
            raise SupermarketSourceError('broken',code='CONTRACT')
        async def okay(_now):
            return good
        with patch('telegrambot.supermarket_closures.SOURCE_FETCHERS',(broken,okay)):
            observations,failures=await collect_observations(now)
        self.assertEqual(observations,(good,))
        self.assertEqual(failures,('broken:CONTRACT',))



if __name__=='__main__': unittest.main()

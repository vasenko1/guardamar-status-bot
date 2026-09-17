from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected block not found in {path}")
    if text.count(old) != 1:
        raise SystemExit(f"expected block is not unique in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found in {path}")
    p.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "src/telegrambot/digest.py",
    '''def _cams_attribution(year: int) -> str:\n    return (\n        f'Источник: <a href="{CAMS_ATTRIBUTION_URL}">Изменённые данные CAMS '\n        f'(Copernicus), {year}</a>. ЕС и ECMWF не несут ответственности за их использование.'\n    )\n''',
    '''def _cams_attribution(year: int) -> str:\n    return (\n        f'Источник: <a href="{CAMS_ATTRIBUTION_URL}">данные CAMS (Copernicus), '\n        f'обработанные для Гуардамара, {year}</a>. '\n        'ЕС и ECMWF не несут ответственности за их использование.'\n    )\n''',
)

replace_once(
    "src/telegrambot/environment_updates.py",
    '''def _cams_attribution(now: datetime) -> str:\n    year = now.astimezone(GUARDAMAR_TIMEZONE).year\n    return (\n        f"<i>Изменённые данные CAMS (Copernicus), {year}. "\n        "ЕС и ECMWF не несут ответственности за их использование.</i>"\n    )\n''',
    '''def _cams_attribution(now: datetime) -> str:\n    year = now.astimezone(GUARDAMAR_TIMEZONE).year\n    return (\n        f"<i>Источник: данные CAMS (Copernicus), обработанные для Гуардамара, {year}. "\n        "ЕС и ECMWF не несут ответственности за их использование.</i>"\n    )\n''',
)

replace_once(
    "src/telegrambot/__main__.py",
    '''    async def edit_current_digest(\n        state: PublicationState,\n        api_key: str,\n        bot_token: str,\n        chat_id: str,\n        *,\n        fetch_cams_remote: bool,\n    ) -> None:\n        """Legacy operator recovery for a day already replaced by an old release."""\n        record = state.morning_record(now.date())\n        if record is None:\n            raise StateError(\n                f"no morning message exists for {now.date().isoformat()}"\n            )\n        if not isinstance(record.get("update_message_id"), int):\n            raise ValueError(\n                "refresh-current is disabled for immutable Morning Digest days"\n            )\n        message_id = _current_morning_message_id(record)\n        fallback = load_snapshot(aemet_snapshot_path, now)\n        refreshed_aemet = []\n        heat_level, cold_level, _ = state.morning_environment(now.date())\n        refreshed_environment = []\n        message = await produce_message(\n            api_key,\n            now,\n            os.environ.get("GEMINI_API_KEY", "").strip(),\n            municipal_path,\n            agenda_state_path=agenda_path,\n            library_agenda_state_path=library_path,\n            am_guardamar_state_path=am_guardamar_path,\n            translation_cache_path=translations_path,\n            aemet_fallback=fallback,\n            aemet_observer=refreshed_aemet.append,\n            pharmacy_state_path=pharmacy_path,\n            cams_data_url=cams_data_url,\n            cams_cache_path=cams_cache_path,\n            fetch_cams_remote=fetch_cams_remote,\n            fetch_meteosalud_data=False,\n            heat_health_fallback=(\n                HeatHealthRisk(heat_level) if heat_level is not None else None\n            ),\n            cold_health_fallback=(\n                ColdHealthRisk(cold_level) if cold_level is not None else None\n            ),\n            environment_observer=lambda heat, cold, base: refreshed_environment.append(\n                (heat, cold, base)\n            ),\n        )\n''',
    '''    async def edit_current_digest(\n        state: PublicationState,\n        api_key: str,\n        bot_token: str,\n        chat_id: str,\n        *,\n        fetch_cams_remote: bool,\n    ) -> None:\n        """Explicitly re-render today's existing Morning Digest in place."""\n        record = state.morning_record(now.date())\n        if record is None:\n            raise StateError(\n                f"no morning message exists for {now.date().isoformat()}"\n            )\n        message_id = _current_morning_message_id(record)\n        fallback = load_snapshot(aemet_snapshot_path, now)\n        refreshed_aemet = []\n        heat_level, cold_level, existing_cams_base = state.morning_environment(\n            now.date()\n        )\n        refreshed_environment = []\n        message = await produce_message(\n            api_key,\n            now,\n            os.environ.get("GEMINI_API_KEY", "").strip(),\n            municipal_path,\n            agenda_state_path=agenda_path,\n            library_agenda_state_path=library_path,\n            am_guardamar_state_path=am_guardamar_path,\n            translation_cache_path=translations_path,\n            aemet_digest=fallback,\n            fetch_aemet=fallback is None,\n            aemet_fallback=fallback,\n            aemet_observer=refreshed_aemet.append,\n            pharmacy_state_path=pharmacy_path,\n            cams_data_url=cams_data_url,\n            cams_cache_path=cams_cache_path,\n            fetch_cams_remote=fetch_cams_remote,\n            fetch_meteosalud_data=False,\n            heat_health_fallback=(\n                HeatHealthRisk(heat_level) if heat_level is not None else None\n            ),\n            cold_health_fallback=(\n                ColdHealthRisk(cold_level) if cold_level is not None else None\n            ),\n            environment_detail_observer=(\n                lambda heat, cold, air, pollen, base: refreshed_environment.append(\n                    (heat, cold, air, pollen, base)\n                )\n            ),\n        )\n''',
)

replace_once(
    "src/telegrambot/__main__.py",
    '''        if refreshed_environment:\n            heat, cold, base = refreshed_environment[-1]\n            state.mark_morning_environment(\n                now.date(),\n                heat.level if heat is not None else None,\n                base,\n                cold_level=cold.level if cold is not None else None,\n            )\n        logging.info("Legacy current digest %s refreshed", message_id)\n''',
    '''        if refreshed_environment:\n            heat, cold, air, pollen, base = refreshed_environment[-1]\n            effective_base = base if base is not None else existing_cams_base\n            state.mark_morning_environment(\n                now.date(),\n                heat.level if heat is not None else None,\n                effective_base,\n                cold_level=cold.level if cold is not None else None,\n            )\n            if base is not None:\n                state.mark_cams_environment(now.date(), base, air, pollen)\n                try:\n                    _promote_cams_snapshot(cams_cache_path, now, base)\n                except EnvironmentError as exc:\n                    logging.warning(\n                        "Manual refresh CAMS snapshot could not be promoted: %s", exc\n                    )\n                else:\n                    prune_cams_candidates(cams_cache_path, base)\n        logging.info("Current digest %s refreshed in place", message_id)\n''',
)

replace_all(
    "tests/test_environment_updates.py",
    "Изменённые данные CAMS (Copernicus), 2026",
    "Источник: данные CAMS (Copernicus), обработанные для Гуардамара, 2026",
)
replace_all(
    "tests/test_environment_updates.py",
    "Изменённые данные CAMS",
    "Источник: данные CAMS",
)
replace_all(
    "tests/test_digest.py",
    "Изменённые данные CAMS (Copernicus), 2026",
    "данные CAMS (Copernicus), обработанные для Гуардамара, 2026",
)

replace_once(
    "tests/test_main.py",
    '''    async def test_refresh_current_rejects_immutable_morning(self):\n        with tempfile.TemporaryDirectory() as directory:\n            state_path = Path(directory) / "delivery.json"\n            now = datetime.now(MADRID)\n            state = PublicationState(state_path)\n            state.mark_morning(now.date(), 10, now)\n            with patch.dict(os.environ, {\n                "AEMET_API_KEY": "aemet",\n                "TELEGRAM_BOT_TOKEN": "telegram",\n                "TELEGRAM_CHAT_ID": "group",\n                "MORNING_DIGEST_STATE_PATH": str(state_path),\n            }):\n                with self.assertRaises(ValueError):\n                    await _run_command("refresh-current")\n''',
    '''    async def test_refresh_current_edits_immutable_morning_in_place(self):\n        with tempfile.TemporaryDirectory() as directory:\n            state_path = Path(directory) / "delivery.json"\n            now = datetime.now(MADRID)\n            state = PublicationState(state_path)\n            state.mark_morning(now.date(), 10, now)\n            edited = AsyncMock()\n\n            async def produce(*args, **kwargs):\n                self.assertIsNone(kwargs["aemet_digest"])\n                self.assertTrue(kwargs["fetch_aemet"])\n                return "обновлённое утреннее сообщение"\n\n            with (\n                patch.dict(os.environ, {\n                    "AEMET_API_KEY": "aemet",\n                    "TELEGRAM_BOT_TOKEN": "telegram",\n                    "TELEGRAM_CHAT_ID": "group",\n                    "MORNING_DIGEST_STATE_PATH": str(state_path),\n                }),\n                patch("telegrambot.__main__.produce_message", new=produce),\n                patch("telegrambot.__main__.edit_message", new=edited),\n                patch("telegrambot.__main__.load_snapshot", return_value=None),\n            ):\n                self.assertEqual(await _run_command("refresh-current"), 0)\n\n            edited.assert_awaited_once_with(\n                "telegram", "group", 10, "обновлённое утреннее сообщение"\n            )\n            self.assertIsNone(\n                PublicationState(state_path).morning_record(now.date())[\n                    "update_message_id"\n                ]\n            )\n''',
)

Path("tests/test_cams_attribution.py").write_text(
    '''import unittest\nfrom datetime import datetime\nfrom zoneinfo import ZoneInfo\n\nfrom telegrambot.digest import _cams_attribution as morning_attribution\nfrom telegrambot.environment_updates import _cams_attribution as update_attribution\n\n\nMADRID = ZoneInfo("Europe/Madrid")\n\n\nclass CamsAttributionTests(unittest.TestCase):\n    def test_morning_attribution_uses_processed_for_guardamar_wording(self):\n        message = morning_attribution(2026)\n        self.assertIn("Источник: <a href=", message)\n        self.assertIn(\n            "данные CAMS (Copernicus), обработанные для Гуардамара, 2026",\n            message,\n        )\n        self.assertIn(\n            "ЕС и ECMWF не несут ответственности за их использование.", message\n        )\n        self.assertNotIn("Изменённые данные", message)\n\n    def test_late_update_attribution_matches_morning_wording(self):\n        message = update_attribution(\n            datetime(2026, 9, 17, 10, 30, tzinfo=MADRID)\n        )\n        self.assertIn(\n            "Источник: данные CAMS (Copernicus), обработанные для Гуардамара, 2026",\n            message,\n        )\n        self.assertIn(\n            "ЕС и ECMWF не несут ответственности за их использование.", message\n        )\n        self.assertNotIn("Изменённые данные", message)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)

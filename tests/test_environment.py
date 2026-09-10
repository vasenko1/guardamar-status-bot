import unittest
import io
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegrambot.environment import _read_netcdf_zip, parse_meteosalud_level, summarize_cams


MADRID = ZoneInfo("Europe/Madrid")


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 4, 7, 30, tzinfo=MADRID)

    def test_meteosalud_levels_and_stale_page(self):
        for level, label in enumerate(("Ausencia de riesgo", "Bajo riesgo", "Riesgo medio", "Riesgo alto")):
            result = parse_meteosalud_level(
                f"<h1>Litoral sur</h1> 04/08/26 Nivel de alerta {label} Previsión".encode(), self.now
            )
            self.assertEqual(result.level, level)
        self.assertIsNone(parse_meteosalud_level(b"03/08/26 Ausencia de riesgo", self.now))

    def test_uses_official_trailing_windows_and_local_day(self):
        now = self.now.replace(hour=23, minute=30)
        start = datetime(2026, 8, 3, 0, tzinfo=timezone.utc)
        rows = []
        for hour in range(48):
            moment = start + timedelta(hours=hour)
            rows.append((moment, {
                "particulate_matter_10um": 101.0 if hour >= 22 else 20.0,
                "particulate_matter_2.5um": 10.0,
                "ozone": 60.0, "nitrogen_dioxide": 20.0,
                "sulphur_dioxide": 20.0,
            }))
        air, pollen = summarize_cams(rows, now)
        self.assertIsNotNone(air)
        self.assertEqual(air.pollutants, ("PM10",))
        self.assertIsNone(pollen)

    def test_pollen_thresholds_and_ragweed_presence(self):
        rows = []
        for hour in range(24):
            rows.append((datetime(2026, 8, 4, hour, tzinfo=MADRID), {
                "olive_pollen": 201.0 if hour >= 15 else 200.0,
                "grass_pollen": 51.0 if hour == 13 else 0.0,
                "ragweed_pollen": 3.0 if hour == 19 else 2.9,
            }))
        air, pollen = summarize_cams(rows, self.now)
        self.assertIsNone(air)
        self.assertEqual(pollen.allergens, ("злаковых трав", "оливы"))
        self.assertTrue(pollen.ragweed_present)

    def test_reads_one_nearest_grid_point_from_netcdf_zip(self):
        from netCDF4 import Dataset

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "particulate_matter_10um.nc"
            with Dataset(path, "w") as document:
                document.createDimension("time", 1)
                document.createDimension("latitude", 2)
                document.createDimension("longitude", 2)
                times = document.createVariable("time", "f8", ("time",))
                times.units = "hours since 2026-08-04 00:00:00"
                times[:] = [0]
                document.createVariable("latitude", "f4", ("latitude",))[:] = [38.0, 38.1]
                document.createVariable("longitude", "f4", ("longitude",))[:] = [-0.7, -0.6]
                values = document.createVariable("particulate_matter_10um", "f4", ("time", "latitude", "longitude"))
                values[:] = [[[1, 2], [3, 4]]]
            with io.BytesIO() as archive_buffer:
                with zipfile.ZipFile(archive_buffer, "w") as archive:
                    archive.write(path, path.name)
                rows = tuple(_read_netcdf_zip(archive_buffer.getvalue()))
        self.assertEqual(rows[0][1]["particulate_matter_10um"], 3.0)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path

path = Path("tools/tmp_apply_aemet_warning_ux.py")
text = path.read_text(encoding="utf-8")
text = text.replace("write_text(r'''import io", 'write_text(r"""import io', 1)
text = text.replace("\n''', encoding=\"utf-8\")", '\n""", encoding="utf-8")', 1)
path.write_text(text, encoding="utf-8")

from pathlib import Path

path = Path("src/telegrambot/digest.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    '            health_indent = "      " if period_first else "   "\n',
    '            health_indent = "   "\n',
    1,
)
block = '''                if period_first:\n                    lines = ["   " + line for line in lines]\n                blocks.extend(lines)\n'''
if text.count(block) != 2:
    raise SystemExit("expected two health-indent blocks")
text = text.replace(block, '                blocks.extend(lines)\n', 2)
path.write_text(text, encoding="utf-8")

from pathlib import Path

path = Path("src/telegrambot/operational_updates.py")
text = path.read_text(encoding="utf-8")
old = '''    current_events = {
        item.get("event", "").casefold() for item in current
    }
'''
new = '''    changed_events = {
        identity[0] for identity in added_or_changed
    }
'''
if text.count(old) != 1:
    raise SystemExit("expected current_events block once")
text = text.replace(old, new, 1)
old = '''        if item.get("event", "").casefold() in current_events:
            removed_relevant = True
        else:
            early_cancelled.append(item)
'''
new = '''        event_key = item.get("event", "").casefold()
        same_context_other_parameter = (
            item.get("parameter_code") is not None
            and any(
                candidate.get("event", "").casefold() == event_key
                and candidate.get("starts_at") == item.get("starts_at")
                and candidate.get("ends_at") == item.get("ends_at")
                and candidate.get("parameter_code") != item.get("parameter_code")
                for candidate in current
            )
        )
        if event_key in changed_events or same_context_other_parameter:
            removed_relevant = True
        else:
            early_cancelled.append(item)
'''
if text.count(old) != 1:
    raise SystemExit("expected removed-warning branch once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

test_path = Path("tests/test_operational_updates.py")
tests = test_path.read_text(encoding="utf-8")
old = '        self.assertEqual(message.count("Обновление AEMET"), 1)\n'
new = '        self.assertEqual(message.count("AEMET обновила предупреждения"), 1)\n'
if tests.count(old) != 1:
    raise SystemExit("expected old AEMET title assertion once")
test_path.write_text(tests.replace(old, new, 1), encoding="utf-8")

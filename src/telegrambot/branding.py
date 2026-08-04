"""Shared compact attribution for public Telegram messages."""

GROUP_URL = "https://t.me/MarketGuardamar"
FOOTER = (
    '📣 <a href="https://t.me/MarketGuardamar">'
    "<b>обЪявления Гуардамар</b></a>"
)


def with_footer(message: str) -> str:
    """Append the forwarding-safe group link exactly once."""

    value = message.rstrip()
    if FOOTER in value:
        return value
    return f"{value}\n\n{FOOTER}"

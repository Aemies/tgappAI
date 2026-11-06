from radar_bot.presenters import EventCard, TextPresenter


def test_text_presenter_escapes_and_links():
    card = EventCard(company='ООО "<РОМАШКА>"', inn="7707083893", title="Смена руководителя", date="2026-11-05", app_path="/clients/1")
    out = TextPresenter().render(card, "https://app.example.ru/")
    assert "&lt;РОМАШКА&gt;" in out["text"]
    assert out["reply_markup"].inline_keyboard[0][0].web_app.url == "https://app.example.ru/clients/1"

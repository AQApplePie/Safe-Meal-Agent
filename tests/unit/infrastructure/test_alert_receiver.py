from SafeMealAgent.back.infrastructure.operations.alert_receiver import AlertInbox


def test_alert_inbox_persists_and_tails_notifications(tmp_path) -> None:
    inbox = AlertInbox(tmp_path / "alerts.jsonl")
    inbox.append({"group_key": "one", "alert_count": 1})
    inbox.append({"group_key": "two", "alert_count": 2})

    assert inbox.tail(1) == [{"group_key": "two", "alert_count": 2}]
    assert len(inbox.tail(10)) == 2

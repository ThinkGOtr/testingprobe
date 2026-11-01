"""Locator onarımı (TEKNIK-TASARIM §8.7): `POST /failures/{id}/fix` → deterministik bot PR.

Diğer şeritler için:

    from tp_core.features.repair import service, views
    service.repair_script_for_pr(session, number)      # PR bir onarıma mı ait?
    service.request_merge(session, number, user, icerik_hash, head_sha)  # /prs/{n}/merge
    views.oneri_blogu(session, failure_id)              # GET /failures/{id} `oneri` bloğu
    views.pr_response(session, number)
"""

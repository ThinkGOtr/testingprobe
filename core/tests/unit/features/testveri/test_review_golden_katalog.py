"""case_review / case_audit golden'ları tohumlu test verisi kataloğuyla da REPLAY olur (REPLAY-MISS
düzeltmesi, 2026-11-15).

Canlı demoda katalog demo-app seed'inden tohumludur; üretilen case'ler kaydedilirken değerleri
`{veri:<anahtar>}` atfına çevrilir ve setin kimliği (`set_hash`) eşlenmiş içerikten hesaplanır.
Golden beyanı yalnız ham setin kimliğini taşıdığında review / denetim her seferinde REPLAY-MISS
düşüyordu. Bu test ürünün GERÇEK kayıt yolunu (`store_cases` → `review.snapshot` →
`review_messages`) gerçek Postgres ve tohumlu katalogla koşar ve girdinin golden beyanına uyduğunu
denetler.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests.unit.gateway import build_review_goldens as brg
from tests.unit.gateway.build_eval_sets import _golden_set
from tests.unit.gateway.demo_sources import demo_query, load_golden
from tp_core.features.cases import review, service
from tp_core.features.testveri import service as testveri
from tp_core.gateway.matching import input_mismatches
from tp_core.models import Requirement, session_scope

ADLAR = [*brg.GOLDENLER, *brg.VARYANTLAR]


@pytest.mark.parametrize("ad", ADLAR)
def test_tohumlu_katalogla_kaydedilen_set_golden_beyanina_uyar(
    engine: Engine, make_requirement: Any, parola_sirri: str, ad: str
) -> None:
    # Katalog GERÇEK demo-app seed'inden (canlıdaki `tohumla` ile aynı; fikstürdeki
    # `SEED_ROWS` kısaltılmış örnektir, kampanya kodu canlıdan farklı).
    with session_scope() as s:
        assert testveri.tohumla(s, demo_query) > 0
    gen_ad, cases = brg.golden_set_cases(ad)
    greq, _, _ = _golden_set(gen_ad)
    rid = make_requirement(greq.jira_key, greq.baslik, greq.aciklama, list(greq.kabul_kriterleri))
    with session_scope() as s:
        req = s.get(Requirement, rid)
        assert req is not None
        eklenen, tekrar = service.store_cases(
            s, req, cases, uretim_no=1, kanal="portal", ai_call_id=None, uretim_modu="replay"
        )
        assert tekrar == [] and len(eklenen) == len(cases)
        # Katalog gerçekten devrede: en az bir case atıf taşır.
        assert any("{veri:" in str(tc.icerik) for tc in eklenen)
        girdi = review.snapshot(s, req)
        messages = review.review_messages(
            req,
            [tc.icerik for tc in girdi.cases],
            girdi.ozet,
            girdi.matris,
            girdi.oranlar,
            girdi.set_hash or "",
        )
        hash_ = girdi.set_hash
    assert hash_ == brg.set_hash_of(brg.mapped_cases(cases))
    for amac in ("case_review", "case_audit"):
        spec = load_golden(amac, ad)["input_match"]
        assert any(hash_ in satir for satir in spec["contains_any"][0]), (amac, ad)
    assert input_mismatches(load_golden("case_review", ad)["input_match"], messages) == []

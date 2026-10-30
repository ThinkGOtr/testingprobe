"""core durum makinelerini (tp_core.workflow.states.MACHINES) JSON olarak basar.

Portal durum birlikleri bu dosyayla karşılaştırılır (src/api/sozlesme.test.ts). Yeniden üretmek:

    npm run sozlesme:durumlar

(`uv run --project ../core python scripts/durum_makineleri.py > src/api/sozlesme/durum-makineleri.json`)
"""

import json
import sys

from tp_core.workflow.states import MACHINES


def main() -> None:
    cikti = {
        ad: {
            "initial": m.initial,
            "states": sorted(m.states),
            "transitions": {k: sorted(v) for k, v in sorted(m.transitions.items())},
        }
        for ad, m in sorted(MACHINES.items())
    }
    json.dump(cikti, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

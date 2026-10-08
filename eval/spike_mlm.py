#!/usr/bin/env python3
"""W0 spike: masked-LM suggestions for flagged Serbian words.

Tier-1 candidates: JelenaTosic/SRBerta (RobertaForMaskedLM).
Note: classla/bcms-bertic is ElectraForPreTraining (discriminator) — NOT an MLM;
kept as optional candidate-scorer, spiked separately.
"""
import sys
import time

import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer

# Probe: (masked sentence, intended word). Crafted around typical ASR garbles
# and informal podcast register.
PROBES = [
    ("On je <mask> sam kroz ceo život.", "prošao"),
    ("To nije bilo <mask> za njega.", "lako"),
    ("Imali smo <mask> na treningu juče.", "sparane"),
    ("Ona je osvojila <mask> medalju na Olimpijadi.", "zlatnu"),
    ("Ne znam <mask> da ti kažem iskreno.", "šta"),
    ("Dolazimo na <mask> mesto svake godine.", "isto"),
    ("To je <mask> najbolji rezultat sezone.", "bio"),
    ("On je <mask> jak igrač u ringu.", "veoma"),
]

MODELS = ["JelenaTosic/SRBerta"]


def main():
    for mid in MODELS:
        t0 = time.time()
        try:
            tok = AutoTokenizer.from_pretrained(mid)
            mdl = AutoModelForMaskedLM.from_pretrained(mid)
        except Exception as e:
            print(f"{mid}: LOAD FAIL {e}")
            continue
        print(f"{mid}: loaded in {time.time()-t0:.0f}s")
        mask = tok.mask_token
        hits5 = hits1 = 0
        for sent, want in PROBES:
            text = sent.replace("<mask>", mask)
            inp = tok(text, return_tensors="pt")
            midx = (inp["input_ids"] == tok.mask_token_id).nonzero()[0, 1]
            with torch.no_grad():
                logits = mdl(**inp).logits[0, midx]
            top = torch.topk(logits, 10).indices.tolist()
            cands = [tok.decode([t]).strip() for t in top]
            rank = next((i for i, c in enumerate(cands) if c.lower() == want), None)
            hits5 += rank is not None and rank < 5
            hits1 += rank == 0
            print(f"  want={want:10} got={cands[:5]}  rank={rank}")
        print(f"{mid}: top1={hits1}/{len(PROBES)} top5={hits5}/{len(PROBES)}")


if __name__ == "__main__":
    main()

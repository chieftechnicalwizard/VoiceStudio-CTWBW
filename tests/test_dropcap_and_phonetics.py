import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.pipeline_v3 import (
    mend_dropcap_and_inline_splits,
    apply_expanse_phonetics,
    validate_manifest_formatting_integrity
)

def test_mend_dropcap_and_inline_splits():
    # Standard dropcaps
    assert mend_dropcap_and_inline_splits("W hat are you doing?") == "What are you doing?"
    assert mend_dropcap_and_inline_splits('"W hat does that mean?" Basia asked.') == '"What does that mean?" Basia asked.'
    assert mend_dropcap_and_inline_splits("T he Scopuli had been taken") == "The Scopuli had been taken"
    assert mend_dropcap_and_inline_splits("M iller stood by the door.") == "Miller stood by the door."
    assert mend_dropcap_and_inline_splits("H olden looked at the screen.") == "Holden looked at the screen."
    assert mend_dropcap_and_inline_splits("C hrisjen Avasarala spoke.") == "Chrisjen Avasarala spoke."

    # Possessive splits
    assert mend_dropcap_and_inline_splits("The Knight 's landing gear") == "The Knight's landing gear"
    assert mend_dropcap_and_inline_splits("The Roci 's hull groaned.") == "The Roci's hull groaned."
    assert mend_dropcap_and_inline_splits("I 've got a plan.") == "I've got a plan."

    # A/I dropcaps
    assert mend_dropcap_and_inline_splits("A fter they arrived") == "After they arrived"
    assert mend_dropcap_and_inline_splits("A bout five hours") == "About five hours"
    assert mend_dropcap_and_inline_splits("I t pinged us, Alex said.") == "It pinged us, Alex said."
    assert mend_dropcap_and_inline_splits("I f they meet again") == "If they meet again"
    assert mend_dropcap_and_inline_splits("I n the end") == "In the end"

    # Preserves valid English articles and nouns (no false positives)
    assert mend_dropcap_and_inline_splits("A long time ago") == "A long time ago"
    assert mend_dropcap_and_inline_splits("A long, low alien structure") == "A long, low alien structure"
    assert mend_dropcap_and_inline_splits("A way out.") == "A way out."
    assert mend_dropcap_and_inline_splits("A head poked up") == "A head poked up"

    # Smallcaps boundary fusion healing
    assert mend_dropcap_and_inline_splits("GETTING BACK TObusiness as usual") == "Getting back to business as usual"
    assert mend_dropcap_and_inline_splits("CHRISTMAS DAY WENTby in a blur.") == "Christmas day went by in a blur."
    assert mend_dropcap_and_inline_splits("IDed the suspect and was IDing the driver") == "IDed the suspect and was IDing the driver"

def test_apply_expanse_phonetics():
    sample = "The Donnager and the Rocinante, or the Roci, were accompanied by the Nauvoo. Chrisjen Avasarala contacted Alex Kamal, Marco Inaros, and Camina Drummer. Belters on Ilus studied the protomolecule."
    result = apply_expanse_phonetics(sample)
    assert "Doniger" in result
    assert "Rocinante" in result
    assert "Rossi" in result
    assert "Inaross" in result

    # Lang Belta Creole de-hyphenation assertions
    belta_sample = "Oy-ay, beh-raht-nah! Look at the Wel-wah-lah speaking to Een-yah-low-dah. Mee boh-roh said SAY-SAH was arrested by Koh-pah-kee-stahn. Yah-meng shouted for the belta."
    belta_res = apply_expanse_phonetics(belta_sample)
    assert "Oye" in belta_res
    assert "Welwala" in belta_res
    assert "Inyalowda" in belta_res
    assert "Mi boro" in belta_res
    assert "Sesa" in belta_res
    assert "Kopakistan" in belta_res
    assert "Yameng" in belta_res

def test_validate_manifest_formatting_integrity():
    manifest_path = "output/staging_the_expanse/leviathan_wakes/thoughts_manifest.json"
    if not os.path.exists(manifest_path):
        pytest.skip("Local staging manifest not present in CI")
    is_clean, issues = validate_manifest_formatting_integrity(manifest_path)
    assert is_clean is True
    assert len(issues) == 0


def test_contextual_paralinguistics_and_qa_stripping():
    from scripts.pipeline_v3.normalizer import inject_contextual_paralinguistics, normalize_numbers_and_currency
    from scripts.pipeline_v3.qa_gate import compute_qa_accuracy

    t1, inst1 = inject_contextual_paralinguistics('"I suppose there is no other way," he sighed.')
    assert "[sigh]" in t1
    assert inst1 is None
    assert compute_qa_accuracy(t1, "I suppose there is no other way, he sighed.") == 1.0

    t2, inst2 = inject_contextual_paralinguistics('"That was easier than expected," she chuckled softly.')
    assert "[laughter]" in t2
    assert compute_qa_accuracy(t2, "That was easier than expected, she chuckled softly.") == 1.0

    t3, inst3 = inject_contextual_paralinguistics("Breathe in... and feel your whole body calm.")
    assert "[pause 350ms]" in t3
    assert "[pause 350ms]" in normalize_numbers_and_currency(t3)
    assert compute_qa_accuracy(t3, "Breathe in and feel your whole body calm.") == 1.0

    t4, inst4 = inject_contextual_paralinguistics('"Do not make a sound," she whispered.')
    assert inst4 == "whisper"

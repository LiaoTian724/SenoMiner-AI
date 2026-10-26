"""Exact experiment-level evaluation, following the TPD assay-record boundary.

This is a new deterministic evaluator, not the upstream CAPO semantic evaluator.
Reported units and qualifiers remain significant; no LLM judges are involved.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .export import load_jsonl_rows
from .validation import KEY_FIELDS, normalized


def evaluate(predicted: list[dict], gold: list[dict]) -> dict:
    def signature(row):
        return tuple(normalized(row.get(key)).casefold() for key in KEY_FIELDS)
    predicted_records = Counter(signature(row) for row in predicted)
    gold_records = Counter(signature(row) for row in gold)
    correct = sum((predicted_records & gold_records).values())
    precision = correct / len(predicted) if predicted else 0.0
    recall = correct / len(gold) if gold else 0.0
    compounds_pred = {normalized(row.get('compound_name')).casefold() for row in predicted} - {''}
    compounds_gold = {normalized(row.get('compound_name')).casefold() for row in gold} - {''}
    compound_correct = len(compounds_pred & compounds_gold)
    return {
        'method': 'exact experiment tuple after whitespace/case normalization; no unit conversion',
        'predicted_records': len(predicted), 'gold_records': len(gold), 'correct_records': correct,
        'experiment_precision': precision, 'experiment_recall': recall,
        'experiment_f1': 2*precision*recall/(precision+recall) if precision+recall else 0.0,
        'compound_precision': compound_correct/len(compounds_pred) if compounds_pred else 0.0,
        'compound_recall': compound_correct/len(compounds_gold) if compounds_gold else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predicted', type=Path, required=True)
    parser.add_argument('--gold', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(load_jsonl_rows(args.predicted), load_jsonl_rows(args.gold)), indent=2))


if __name__ == '__main__':
    main()

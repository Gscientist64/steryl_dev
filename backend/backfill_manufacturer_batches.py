"""
One-off backfill for legacy manufacturer batches.

Legacy manufacturer batch creation stored ProductSKU ids in batch.product_id.
This script safely migrates only the old manufacturer-generated rows that match
the historical BATCH-* numbering pattern.
"""
from __future__ import annotations

import argparse

from app import create_app, db
from app.models import Batch, Product, ProductSKU


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill legacy manufacturer batches")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the backfill. Without this flag, the script runs as a dry run.",
    )
    parser.add_argument(
        "--prefix",
        default="BATCH-",
        help="Batch number prefix used by the legacy manufacturer flow.",
    )
    return parser.parse_args()


def find_legacy_batches(prefix: str) -> list[Batch]:
    return (
        Batch.query.filter(
            Batch.product_sku_id.is_(None),
            Batch.product_id.isnot(None),
            Batch.batch_number.like(f"{prefix}%"),
        )
        .order_by(Batch.id.asc())
        .all()
    )


def backfill_batches(apply_changes: bool, prefix: str) -> int:
    app = create_app()

    with app.app_context():
        candidates = find_legacy_batches(prefix)

        if not candidates:
            print("No legacy manufacturer batches found.")
            return 0

        updated = 0
        skipped = 0

        print(f"Found {len(candidates)} legacy manufacturer batch candidate(s).")

        for batch in candidates:
            product_sku = db.session.get(ProductSKU, batch.product_id)
            global_product = db.session.get(Product, batch.product_id)

            if not product_sku:
                skipped += 1
                print(
                    f"SKIP batch_id={batch.id} batch_number={batch.batch_number} "
                    f"product_id={batch.product_id} reason=no matching ProductSKU"
                )
                continue

            print(
                f"MAP batch_id={batch.id} batch_number={batch.batch_number} "
                f"legacy_product_id={batch.product_id} "
                f"global_product={getattr(global_product, 'name', None)!r} "
                f"manufacturer_product={product_sku.name!r} "
                f"manufacturer_id={product_sku.manufacturer_id}"
            )

            if apply_changes:
                batch.product_sku_id = product_sku.id
                batch.product_id = None

            updated += 1

        if apply_changes:
            db.session.commit()
            print(f"Applied backfill to {updated} batch(es).")
        else:
            db.session.rollback()
            print(f"Dry run complete. {updated} batch(es) would be updated.")

        if skipped:
            print(f"Skipped {skipped} batch(es).")

        return updated


if __name__ == "__main__":
    args = parse_args()
    backfill_batches(apply_changes=args.apply, prefix=args.prefix)
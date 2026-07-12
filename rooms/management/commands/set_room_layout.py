import math

from django.core.management.base import BaseCommand

from rooms.models import Room


def layout_for_capacity(capacity: int) -> tuple[int, int]:
    """
    Pick a near-square (rows, columns) grid that fits at least `capacity`
    seats, matching RoomSerializer's validation (rows * columns >= capacity).
    """
    columns = math.ceil(math.sqrt(capacity))
    rows = math.ceil(capacity / columns)
    return rows, columns


class Command(BaseCommand):
    help = (
        "Backfill rows/columns (seat map layout) for rooms based on their "
        "capacity. Skips rooms that already have a layout unless --force "
        "is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute rows/columns even for rooms that already have a layout.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without saving anything.",
        )
        parser.add_argument(
            "--location",
            type=str,
            default=None,
            help="Only update rooms in this location (matched by name).",
        )

    def handle(self, *args, **options):
        force = options["force"]
        dry_run = options["dry_run"]
        location_name = options["location"]

        rooms = Room.objects.all().order_by("name")
        if location_name:
            rooms = rooms.filter(location__name=location_name)
        if not force:
            rooms = rooms.filter(rows__isnull=True) | rooms.filter(columns__isnull=True)

        updated = 0
        for room in rooms:
            if not room.capacity:
                self.stdout.write(
                    self.style.WARNING(f"Skipping '{room.name}': no capacity set.")
                )
                continue

            rows, columns = layout_for_capacity(room.capacity)
            self.stdout.write(
                f"{room.name}: capacity={room.capacity} -> "
                f"rows={rows}, columns={columns} ({rows * columns} seats)"
            )

            if not dry_run:
                room.rows = rows
                room.columns = columns
                room.save(update_fields=["rows", "columns"])
            updated += 1

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {updated} room(s)."))

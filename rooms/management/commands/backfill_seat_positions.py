from django.core.management.base import BaseCommand

from exams.models import StudentExam
from rooms.models import Room
from schedules.utils import assign_seat_positions_for_room_slot


class Command(BaseCommand):
    help = (
        "Assign row/column seat positions to students who already have a "
        "room but no seat position — happens for any StudentExam created "
        "before its room had rows/columns set, since "
        "assign_seat_positions_for_room_slot is a no-op on unlaid-out "
        "rooms and only runs once, at generation time."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be processed without assigning anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        slots = (
            StudentExam.objects.filter(room__isnull=False, seat_row__isnull=True)
            .values_list(
                "room_id", "exam__date", "exam__start_time", "exam__end_time"
            )
            .distinct()
        )
        slots = list(slots)

        self.stdout.write(f"Found {len(slots)} room/date/slot combinations to backfill.")

        rooms_by_id = {r.id: r for r in Room.objects.all()}
        processed = 0
        skipped_no_layout = 0

        for room_id, date, start_time, end_time in slots:
            room = rooms_by_id.get(room_id)
            if not room:
                continue
            if not room.has_seat_layout():
                skipped_no_layout += 1
                continue

            self.stdout.write(f"{room.name} | {date} [{start_time}-{end_time}]")
            if not dry_run:
                assign_seat_positions_for_room_slot(room, date, start_time, end_time)
            processed += 1

        verb = "Would process" if dry_run else "Processed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {processed} room/slot combination(s). "
                f"Skipped {skipped_no_layout} still missing a room layout."
            )
        )

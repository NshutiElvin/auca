import collections
from dataclasses import dataclass, field
from typing import List, Dict, Tuple

@dataclass
class Room:
    id: int
    capacity: int

@dataclass
class Course:
    id: int
    name: str

@dataclass
class Exam:
    date: str
    slot: str
    course: str

# Mocking the new Slot-based logic
def simulate_schedule_logic(courses_with_size, total_seats, total_slots):
    # 1. Grouping (Simplified Coloring)
    # Target: Maximize packing into groups of size <= total_seats
    
    # Sort courses largest first
    sorted_courses = sorted(courses_with_size, key=lambda x: -x[1])
    
    groups = []
    
    # Simple First-Fit algorithm
    for course_name, size in sorted_courses:
        placed = False
        for group in groups:
            # group = {"size": int, "courses": list}
            if group["size"] + size <= total_seats:
                group["courses"].append(course_name)
                group["size"] += size
                placed = True
                break
        if not placed:
            groups.append({"size": size, "courses": [course_name]})
            
    # 2. Assigning to Slots
    schedule = []
    
    # Generate slots (D1-M, D1-A, D1-E, D2-M...)
    available_slots = []
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    slot_names = ["Morning", "Afternoon", "Evening"]
    
    for d in days:
        for s in slot_names:
            if d == "Friday" and s == "Evening": continue
            available_slots.append(f"{d} {s}")
            if len(available_slots) >= total_slots: break
        if len(available_slots) >= total_slots: break
            
    print(f"Formed {len(groups)} groups from {len(courses_with_size)} courses.")
    print(f"Available Slots: {len(available_slots)}")
    
    for idx, group in enumerate(groups):
        if idx >= len(available_slots):
            print(f"Warning: Ran out of slots for group {idx}!")
            break
            
        slot = available_slots[idx]
        for course in group["courses"]:
            schedule.append(Exam(date=slot.split()[0], slot=slot.split()[1], course=course))
            
    return schedule

def run_test():
    total_seats = 100 # Room capacity
    
    # Scenario: 
    # 3 big courses (80 students) -> Must be in separate slots
    # 6 small courses (10 students) -> Can share slots
    courses = [
        ("Big1", 80), ("Big2", 80), ("Big3", 80),
        ("Small1", 10), ("Small2", 10), ("Small3", 10),
        ("Small4", 10), ("Small5", 10), ("Small6", 10)
    ]
    
    # With old logic (Group capacity = 300), these might all fit in "1 Day Group".
    # But then 80+80+80=240, fits in 300.
    # Group -> Day.
    # schedule_group_exams tries to fit Big1, Big2, Big3 into Morning, Afternoon, Evening.
    # It would succeed.
    
    # What if we have 5 Big courses?
    # Old Logic: 
    # Group 1: Big1, Big2, Big3 (240 < 300). -> Day 1.
    # Group 2: Big4, Big5 (160 < 300). -> Day 2.
    # Total Days: 2.
    
    # New Logic (Group capacity = 100):
    # Group 1: Big1 (80) + Small1(10) + Small2(10). Total 100. -> Slot 1
    # Group 2: Big2 (80) + Small3(10) + Small4(10). Total 100. -> Slot 2
    # Group 3: Big3 (80) + Small5(10) + Small6(10). Total 100. -> Slot 3
    # ...
    # Total Slots: 3. (Day 1 Morning, Afternoon, Evening).
    # New Logic fits 5 Big courses into 5 Slots (Day 1 + Day 2 Morning/Afternoon).
    
    # This demonstrates packing EFFICIENCY.
    
    print("Testing New Slot-Based Logic:")
    schedule = simulate_schedule_logic(courses, total_seats, 100)
    
    for exam in schedule:
        print(f"{exam.course}: {exam.date} {exam.slot}")
        
    # Validation
    slots_used = set(f"{e.date} {e.slot}" for e in schedule)
    print(f"Total Slots Used: {len(slots_used)}")
    
    if len(slots_used) == 3:
        print("SUCCESS: Packed into 3 slots!")
    else:
        print(f"FAIL: Expected 3 slots, got {len(slots_used)}")

if __name__ == "__main__":
    run_test()

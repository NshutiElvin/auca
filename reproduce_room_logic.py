import collections
from dataclasses import dataclass, field
from typing import List, Dict, Set

# Mock setup
@dataclass
class Room:
    id: int
    capacity: int

@dataclass
class Course:
    id: int
    name: str

@dataclass
class Student:
    id: int

@dataclass(unsafe_hash=True)
class Exam:
    id: int
    course: Course = field(hash=False)
    date: str
    start_time: str
    end_time: str
    slot_name: str

@dataclass
class StudentExam:
    id: int
    student: Student
    exam: Exam
    room: Room = None

# Logic to test (simplified version of the buggy allocate_shared_rooms)
def simulate_allocation_buggy(student_exams, rooms):
    schedule = collections.defaultdict(list) # room_id -> list of assigned exams
    
    # Organize by slot (assuming single slot for this test)
    slot_students = student_exams
    
    exams = collections.defaultdict(list)
    for se in slot_students:
        exams[se.exam].append(se)
        
    sorted_exams = sorted(exams.items(), key=lambda x: -len(x[1]))
    
    remaining_students = slot_students.copy()
    room_index = 0
    
    assigned_count = 0
    
    while remaining_students and room_index < len(rooms):
        room = rooms[room_index]
        room_index += 1
        
        # In current bad logic: we try to fit ONE pair or ONE single, then move to next room
        best_pair = None
        
        # Try to find a pair
        for i in range(len(sorted_exams)):
            exam1, students1 = sorted_exams[i]
            if not students1: continue
            
            for j in range(i + 1, len(sorted_exams)):
                exam2, students2 = sorted_exams[j]
                if not students2: continue
                
                # Simplified pairing logic (always compatible for this test)
                if len(students1) + len(students2) <= room.capacity:
                     best_pair = (exam1, exam2)
                     break
            if best_pair: break
            
        if best_pair:
            exam1, exam2 = best_pair
            # Assign them
            to_assign = [se for se in remaining_students if se.exam == exam1 or se.exam == exam2]
            schedule[room.id].extend(to_assign)
            assigned_count += len(to_assign)
            for se in to_assign:
                if se in remaining_students:
                     remaining_students.remove(se)
                exams[se.exam].remove(se)
        else:
             # Assign single
             for exam, students in sorted_exams:
                 if students and len(students) <= room.capacity:
                     to_assign = [se for se in remaining_students if se.exam == exam]
                     schedule[room.id].extend(to_assign)
                     assigned_count += len(to_assign)
                     for se in to_assign:
                         remaining_students.remove(se)
                         exams[exam].remove(se)
                     break
        
        # BUG: The loop continues to the next room here, even if room has capacity left!
        
    return assigned_count

# New proposed logic
def simulate_allocation_fixed(student_exams, rooms):
    schedule = collections.defaultdict(list)
    slot_students = student_exams
    
    exams = collections.defaultdict(list)
    for se in slot_students:
        exams[se.exam].append(se)
        
    sorted_exams = sorted(exams.items(), key=lambda x: -len(x[1]))
    
    remaining_students = slot_students.copy()
    room_index = 0
    assigned_count = 0
    
    while remaining_students and room_index < len(rooms):
        room = rooms[room_index]
        current_room_occupancy = 0
        
        # Keep trying to fill THIS room until full or no fit
        while True:
            available_capacity = room.capacity - current_room_occupancy
            if available_capacity <= 0:
                break
                
            best_pair = None
            
            # Recalculate sorted exams based on remaining students
            # In a real impl we might optimize this, but for simulation it stands
            current_exam_sizes = []
            for e, s_list in exams.items():
                 # We need students that are still in remaining_students
                 actual_students = [s for s in s_list if s in remaining_students]
                 if actual_students:
                     current_exam_sizes.append((e, actual_students))
            current_exam_sizes.sort(key=lambda x: -len(x[1]))
            
            # Try pair
            pair_found = False
            for i in range(len(current_exam_sizes)):
                e1, s1 = current_exam_sizes[i]
                for j in range(i+1, len(current_exam_sizes)):
                    e2, s2 = current_exam_sizes[j]
                    
                    if len(s1) + len(s2) <= available_capacity:
                        # Assign pair
                        to_assign = s1 + s2
                        schedule[room.id].extend(to_assign)
                        assigned_count += len(to_assign)
                        current_room_occupancy += len(to_assign)
                        for se in to_assign:
                            remaining_students.remove(se)
                         # Update local lists? We rebuild next iter
                        pair_found = True
                        break
                if pair_found: break
            
            if pair_found:
                continue # Try to fill valid space again
                
            # If no pair, try single
            single_found = False
            for e, s in current_exam_sizes:
                if len(s) <= available_capacity:
                    to_assign = s
                    schedule[room.id].extend(to_assign)
                    assigned_count += len(to_assign)
                    current_room_occupancy += len(to_assign)
                    for se in to_assign:
                        remaining_students.remove(se)
                    single_found = True
                    break
            
            if single_found:
                continue
            
            # If we get here, nothing fit in this room
            break
            
        room_index += 1
        
    return assigned_count

def run_test():
    # Setup
    r1 = Room(1, 100) # Capacity 100
    rooms = [r1]
    
    c1 = Course(1, "Data Structures") # 40 students
    c2 = Course(2, "Algorithms")      # 40 students
    c3 = Course(3, "Math")            # 10 students
    c4 = Course(4, "English")         # 10 students
    
    ex1 = Exam(1, c1, "2023-01-01", "08:00", "11:00", "Morning")
    ex2 = Exam(2, c2, "2023-01-01", "08:00", "11:00", "Morning")
    ex3 = Exam(3, c3, "2023-01-01", "08:00", "11:00", "Morning")
    ex4 = Exam(4, c4, "2023-01-01", "08:00", "11:00", "Morning")
    
    students = []
    id_counter = 1
    
    def create_exam_students(exam, count):
        nonlocal id_counter
        for _ in range(count):
            s = Student(id_counter)
            students.append(StudentExam(id_counter, s, exam))
            id_counter += 1
            
    create_exam_students(ex1, 40)
    create_exam_students(ex2, 40)
    create_exam_students(ex3, 10)
    create_exam_students(ex4, 10)
    
    total_students = 100
    
    print(f"Total Students: {total_students}")
    print(f"Room Capacity: 100")
    print(f"Groups: A(40), B(40), C(10), D(10)")
    
    # Run Buggy
    buggy_assigned = simulate_allocation_buggy(students.copy(), rooms)
    print(f"\n[Buggy Logic] Assigned: {buggy_assigned}/{total_students}")
    
    # Run Fixed
    fixed_assigned = simulate_allocation_fixed(students.copy(), rooms)
    print(f"[Fixed Logic] Assigned: {fixed_assigned}/{total_students}")
    
    if fixed_assigned > buggy_assigned:
        print("\nSUCCESS: Fixed logic assigned more students!")
    else:
        print("\nFAIL: No improvement.")

if __name__ == "__main__":
    run_test()

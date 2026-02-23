import sqlite3
import os
import re

IMAGE_FOLDER = "jee_smart_snips"
DB_FOLDER = "databases"

def get_img(p):
    return open(p, 'rb').read() if os.path.exists(p) else None

def bulk_import():
    if not os.path.exists(DB_FOLDER): os.makedirs(DB_FOLDER)
    
    # V7 Upgrade: Name your paper dynamically!
    print("--- JEE Testor Uploader ---")
    paper_name = input("Enter the name for this paper (e.g., Paper_2023): ").strip()
    if not paper_name: paper_name = "Default_Paper"
    if not paper_name.endswith('.db'): paper_name += ".db"
    
    db_file = os.path.join(DB_FOLDER, paper_name)
    
    conn = sqlite3.connect(db_file); c = conn.cursor()
    
    # V7 Schema
    c.execute('''CREATE TABLE IF NOT EXISTS questions (
                 id INTEGER PRIMARY KEY, subject TEXT, chapter TEXT, 
                 question_text TEXT, question_img BLOB,
                 option_a TEXT, option_a_img BLOB, option_b TEXT, option_b_img BLOB,
                 option_c TEXT, option_c_img BLOB, option_d TEXT, option_d_img BLOB,
                 correct_option TEXT, ideal_time_sec INTEGER,
                 question_type TEXT DEFAULT 'Single Correct', 
                 marks_pos INTEGER DEFAULT 3, marks_neg INTEGER DEFAULT 1)''')
                 
    c.execute('''CREATE TABLE IF NOT EXISTS responses (
                 id INTEGER PRIMARY KEY, session_id TEXT, timestamp DATETIME,
                 question_id INTEGER, user_answer TEXT, time_taken_sec INTEGER,
                 is_correct BOOLEAN, category TEXT, manual_review_done BOOLEAN DEFAULT 0,
                 score_awarded INTEGER DEFAULT 0)''')
    
    files = os.listdir(IMAGE_FOLDER)
    q_nums = sorted(list(set([int(re.match(r"Q(\d+)_", f).group(1)) for f in files if re.match(r"Q(\d+)_", f)])))
    
    if not q_nums:
        print(f"⚠️ No images found in {IMAGE_FOLDER}. Run your snipper first!")
        return

    count = 0
    for n in q_nums:
        path = f"{IMAGE_FOLDER}/Q{n}"
        # Inserting with ALL required columns
        c.execute("""INSERT INTO questions 
                     (subject, chapter, question_text, question_img, 
                      option_a_img, option_b_img, option_c_img, option_d_img, 
                      correct_option, ideal_time_sec, question_type, marks_pos, marks_neg) 
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  ('Physics', 'Uncategorized', f'Q{n}', get_img(f"{path}_question.png"), 
                   get_img(f"{path}_A.png"), get_img(f"{path}_B.png"), get_img(f"{path}_C.png"), get_img(f"{path}_D.png"), 
                   'A', 60, 'Single Correct', 3, 1))
        count += 1
        
    conn.commit(); conn.close()
    print(f"🎉 Success! Imported {count} questions into {db_file}")

if __name__ == "__main__": 
    bulk_import()
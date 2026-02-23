# --- CHUNK 1: IMPORTS & CONFIGURATION ---
import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime
import time
import shutil
import os
import random
import glob
import hashlib

st.set_page_config(page_title="JEE Testor", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .block-container { padding-top: 4rem !important; padding-bottom: 5rem; }
    .jee-card {
        background-color: #ffffff !important; color: #000000 !important;
        border: 2px solid #e0e0e0; border-radius: 8px; padding: 20px;
        margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .jee-card h3, .jee-card p, .jee-card div, .jee-card span { color: #000000 !important; }
    .stRadio label, .stCheckbox label { color: #ffffff !important; font-weight: bold; }
    .testor-title { font-size: 4.5rem; font-weight: 800; color: #4A90E2; margin-bottom: 0px; text-align: center; }
    .testor-sub { font-size: 1.5rem; color: #888888; margin-bottom: 30px; text-align: center; }
</style>
""", unsafe_allow_html=True)

BASE_DB_DIR = "databases"
AUTH_DB = os.path.join(BASE_DB_DIR, "users.db")

# --- CHUNK 2: DATABASE ENGINE (MULTI-USER) ---
def hash_pass(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_auth():
    if not os.path.exists(BASE_DB_DIR): os.makedirs(BASE_DB_DIR)
    conn = sqlite3.connect(AUTH_DB)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
    conn.commit(); conn.close()

def get_user_folder():
    folder = os.path.join(BASE_DB_DIR, st.session_state.username)
    if not os.path.exists(folder): os.makedirs(folder)
    return folder

def get_parent_db_path():
    return os.path.join(get_user_folder(), "parent_testor.db")

def get_available_papers():
    folder = get_user_folder()
    files = glob.glob(os.path.join(folder, "*.db"))
    return [f for f in files if "parent" not in f and "backup" not in f]

def init_db(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
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
    conn.commit(); conn.close()

def init_parent_db():
    conn = sqlite3.connect(get_parent_db_path())
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chapter_stats (
                 subject TEXT, chapter TEXT, total_attempted INTEGER DEFAULT 0,
                 correct INTEGER DEFAULT 0, incorrect INTEGER DEFAULT 0,
                 total_time_sec INTEGER DEFAULT 0,
                 PRIMARY KEY (subject, chapter))''')
    conn.commit(); conn.close()

def aclaim_to_parent(child_db_path):
    parent_path = get_parent_db_path()
    if os.path.exists(parent_path):
        shutil.copy(parent_path, os.path.join(get_user_folder(), "backup_parent_testor.db"))
    
    init_parent_db()
    conn_child = sqlite3.connect(child_db_path)
    query = """
        SELECT q.subject, q.chapter, r.is_correct, r.time_taken_sec 
        FROM responses r JOIN questions q ON r.question_id = q.id 
        WHERE r.manual_review_done = 1 AND r.user_answer != '' AND r.user_answer IS NOT NULL
    """
    df = pd.read_sql(query, conn_child)
    conn_child.close()
    
    if df.empty: return False

    df['is_correct'] = df['is_correct'].fillna(0).astype(int)
    stats = df.groupby(['subject', 'chapter']).agg(
        attempted=('is_correct', 'count'), correct=('is_correct', 'sum'), time_sec=('time_taken_sec', 'sum')
    ).reset_index()

    conn_parent = sqlite3.connect(parent_path)
    c = conn_parent.cursor()
    for _, row in stats.iterrows():
        att = int(row['attempted']); corr = int(row['correct'])
        incorr = att - corr; t_sec = int(row['time_sec'])
        chap = str(row['chapter']); subj = str(row['subject'])
        
        c.execute("SELECT * FROM chapter_stats WHERE subject=? AND chapter=?", (subj, chap))
        if c.fetchone():
            c.execute("""UPDATE chapter_stats SET 
                         total_attempted = total_attempted + ?, correct = correct + ?, 
                         incorrect = incorrect + ?, total_time_sec = total_time_sec + ? 
                         WHERE subject = ? AND chapter = ?""", (att, corr, incorr, t_sec, subj, chap))
        else:
            c.execute("""INSERT INTO chapter_stats (subject, chapter, total_attempted, correct, incorrect, total_time_sec) 
                         VALUES (?, ?, ?, ?, ?, ?)""", (subj, chap, att, corr, incorr, t_sec))
    conn_parent.commit(); conn_parent.close()
    return True

def get_questions(db_path):
    init_db(db_path) 
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM questions", conn)
    conn.close()
    return df

# --- CHUNK 3: SESSION STATE ---
states = {
    'app_phase': 'login', # START HERE NOW
    'username': None,
    'selected_paper': None, 
    'q_map': [], 'current_idx': 0, 'responses': {}, 'status': {}, 
    'timers': {}, 'start_time_q': time.time(), 
    'test_start_time_global': time.time(), 'current_session_id': None,
    'is_timed': True, 'test_duration_secs': 10800 
}
for key, val in states.items():
    if key not in st.session_state: st.session_state[key] = val

def change_phase(new_phase):
    st.session_state.app_phase = new_phase
    st.rerun()

# --- CHUNK 4: CORE LOGIC ---
def prepare_test(db_path):
    df = get_questions(db_path)
    if df.empty: return False
    
    subject_order = ["Physics", "Chemistry", "Mathematics", "Uncategorized"]
    for s in df['subject'].unique():
        if s not in subject_order: subject_order.append(s)
        
    type_order = ["Single Correct", "Multi-Correct", "Paragraph", "Integer", "Numerical"]
    final_order = []
    
    for subj in subject_order:
        subj_df = df[df['subject'] == subj]
        if subj_df.empty: continue
        for q_type in type_order:
            subset = subj_df[subj_df['question_type'] == q_type]
            if not subset.empty:
                ids = subset['id'].tolist()
                random.shuffle(ids) 
                final_order.extend(ids)
                
        other_subset = subj_df[~subj_df['question_type'].isin(type_order)]
        if not other_subset.empty:
            ids = other_subset['id'].tolist()
            random.shuffle(ids)
            final_order.extend(ids)

    st.session_state.q_map = final_order
    st.session_state.status = {qid: 'not_visited' for qid in final_order}
    st.session_state.timers = {qid: 0 for qid in final_order}
    st.session_state.responses = {}
    st.session_state.current_idx = 0
    st.session_state.start_time_q = time.time()
    st.session_state.test_start_time_global = time.time() 
    return True

def update_timer():
    if st.session_state.app_phase in ['test', 'summary']:
        now = time.time()
        spent = now - st.session_state.start_time_q
        try:
            q_id = st.session_state.q_map[st.session_state.current_idx]
            st.session_state.timers[q_id] = st.session_state.timers.get(q_id, 0) + spent
        except: pass 
        st.session_state.start_time_q = now

def mark_visited():
    try:
        q_id = st.session_state.q_map[st.session_state.current_idx]
        if q_id not in st.session_state.responses and st.session_state.status.get(q_id) != 'review':
            st.session_state.status[q_id] = 'not_answered'
    except: pass

def submit_test_initial():
    conn = sqlite3.connect(st.session_state.selected_paper, timeout=10)
    c = conn.cursor()
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.session_state.current_session_id = session_id
    
    df_q = get_questions(st.session_state.selected_paper)
    
    for q_id in st.session_state.q_map:
        ans = st.session_state.responses.get(q_id, "")
        t_spent = int(st.session_state.timers.get(q_id, 0))
        q_row = df_q[df_q['id'] == q_id].iloc[0]
        score = 0; is_correct = 0
        
        if ans:
            c_key = str(q_row['correct_option']).strip()
            ans_str = str(ans).strip()
            q_type = q_row['question_type']
            
            if q_type == 'Multi-Correct':
                u_set = set(ans_str.split(',')) if ans_str else set()
                k_set = set(c_key.split(',')) if c_key else set()
                if u_set == k_set and len(u_set) > 0:
                    score = q_row['marks_pos']; is_correct = 1
                elif u_set.issubset(k_set) and len(u_set) > 0: score = len(u_set) 
                else: score = -q_row['marks_neg']
            elif q_type in ['Numerical', 'Integer']:
                try:
                    if float(ans_str) == float(c_key):
                        score = q_row['marks_pos']; is_correct = 1
                    else: score = -q_row['marks_neg']
                except:
                    if ans_str == c_key:
                        score = q_row['marks_pos']; is_correct = 1
                    else: score = -q_row['marks_neg']
            else: 
                if ans_str == c_key:
                    score = q_row['marks_pos']; is_correct = 1
                else: score = -q_row['marks_neg']

        # THE FIX: manual_review_done is set to 1 immediately so it goes to analytics.
        # Default category is "Pending Review"
        c.execute("""INSERT INTO responses 
                     (session_id, timestamp, question_id, user_answer, time_taken_sec, is_correct, score_awarded, category, manual_review_done) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending Review', 1)""", 
                  (session_id, datetime.now(), q_id, str(ans), t_spent, is_correct, int(score)))
    conn.commit(); conn.close()
    
    # Bypass categorization, go straight to analytics
    change_phase('analytics')



# --- CHUNK 5: EXAM INTERFACES ---

def render_login():
    init_auth()
    st.markdown('<h1 class="testor-title">JEE Testor</h1>', unsafe_allow_html=True)
    st.markdown('<p class="testor-sub">Sign in to your personal workspace.</p>', unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([1, 1.5, 1])
    with c2:
        tab1, tab2 = st.tabs(["Login", "Create Account"])
        
        with tab1:
            u_log = st.text_input("Username", key="log_u")
            p_log = st.text_input("Password", type="password", key="log_p")
            if st.button("Access Platform", type="primary", use_container_width=True):
                if u_log and p_log:
                    conn = sqlite3.connect(AUTH_DB)
                    c = conn.cursor()
                    c.execute("SELECT password FROM users WHERE username=?", (u_log,))
                    result = c.fetchone()
                    conn.close()
                    
                    if result and result[0] == hash_pass(p_log):
                        st.session_state.username = u_log
                        change_phase('home')
                    else:
                        st.error("Invalid username or password.")
                else: st.warning("Please fill both fields.")
                
        with tab2:
            u_reg = st.text_input("New Username", key="reg_u")
            p_reg = st.text_input("New Password", type="password", key="reg_p")
            if st.button("Create Profile", type="secondary", use_container_width=True):
                if u_reg and p_reg:
                    conn = sqlite3.connect(AUTH_DB)
                    c = conn.cursor()
                    try:
                        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (u_reg, hash_pass(p_reg)))
                        conn.commit()
                        st.success("Account created! You can now log in.")
                    except sqlite3.IntegrityError:
                        st.error("Username already exists. Choose another.")
                    conn.close()
                else: st.warning("Please fill both fields.")

def render_home():
    st.markdown('<h1 class="testor-title">JEE Testor</h1>', unsafe_allow_html=True)
    st.markdown('<p class="testor-sub">Your personal simulator and tutor.</p>', unsafe_allow_html=True)
    
    papers = get_available_papers()
    if not papers: 
        st.warning("No question papers found in your workspace. Run your uploader!")
        return
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        paper_names = {p: os.path.basename(p).replace('.db', '') for p in papers}
        selected = st.selectbox("Select Question Paper:", papers, format_func=lambda x: paper_names[x])
        
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Proceed to Instructions", type="primary", use_container_width=True):
            st.session_state.selected_paper = selected
            change_phase('instructions')

def render_instructions():
    st.title("📄 Paper Instructions")
    df = get_questions(st.session_state.selected_paper)
    
    if df.empty:
        st.error("This paper has no questions.")
        if st.button("Back"): change_phase('home')
        return

    st.subheader(f"Total Questions: {len(df)}")
    breakdown = df['question_type'].value_counts().reset_index()
    breakdown.columns = ['Question Type', 'Count']
    st.dataframe(breakdown, hide_index=True, use_container_width=True)
    
    st.markdown("---")
    st.subheader("⏱️ Exam Settings")
    is_timed = st.checkbox("Enable Time Limit", value=True)
    duration_mins = 180
    
    if is_timed:
        duration_mins = st.number_input("Test Duration (minutes):", min_value=1, value=180, step=15)
    else:
        st.info("Take as long as you need. Your per-question time will still be tracked.")
    
    st.markdown("---")
    c1, c2 = st.columns([1, 5])
    if c1.button("Start Test", type="primary"):
        st.session_state.is_timed = is_timed
        st.session_state.test_duration_secs = duration_mins * 60 if is_timed else 0
        if prepare_test(st.session_state.selected_paper): 
            change_phase('test')
            
    if c2.button("Cancel"): change_phase('home')

def check_timer():
    elapsed = time.time() - st.session_state.test_start_time_global
    
    if st.session_state.is_timed:
        rem = st.session_state.test_duration_secs - elapsed
        if rem <= 0: return True 
        mins, secs = divmod(int(rem), 60)
        st.markdown(f"### ⏳ Time Left: **{mins:02d}:{secs:02d}**")
        return False
    else:
        mins, secs = divmod(int(elapsed), 60)
        st.markdown(f"### ⏱️ Time Elapsed: **{mins:02d}:{secs:02d}**")
        return False

def render_summary():
    if check_timer():
        st.warning("Time's up! Auto-submitting..."); update_timer(); submit_test_initial(); return
    
    st.title("📊 Test Summary")
    st.info("Please review your status before making the final submission.")
    
    counts = {"answered": 0, "ans_review": 0, "review": 0, "not_answered": 0, "not_visited": 0}
    for v in st.session_state.status.values(): counts[v] = counts.get(v, 0) + 1
        
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**🟢 Attempted (Counted for Marks):** {counts['answered']}")
        st.markdown(f"**🟣✅ Marked for Review & Attempted:** {counts['ans_review']}")
        st.markdown(f"**🟣 Marked for Review:** {counts['review']}")
    with c2:
        st.markdown(f"**🔴 Skipped:** {counts['not_answered']}")
        st.markdown(f"**⚪ Not Visited:** {counts['not_visited']}")
        
    st.markdown("---")
    sc1, sc2 = st.columns([1, 5])
    if sc1.button("⬅️ Back to Test"): change_phase('test')
    if sc2.button("Final Submit", type="primary"): submit_test_initial()

def render_test_interface():
    if check_timer():
        st.warning("Time's up! Auto-submitting..."); update_timer(); submit_test_initial(); return

    df_questions = get_questions(st.session_state.selected_paper)
    col_q, col_p = st.columns([3.5, 1.5])
    
    current_q_id = st.session_state.q_map[st.session_state.current_idx]
    current_subj = df_questions.loc[df_questions['id'] == current_q_id, 'subject'].values[0]

    with col_p:
        st.markdown("#### Question Palette")
        if st.button("SUBMIT TEST", type="primary", use_container_width=True):
            update_timer(); mark_visited(); change_phase('summary')
        st.markdown("---")

        subjects_in_map = []
        for qid in st.session_state.q_map:
            s = df_questions.loc[df_questions['id'] == qid, 'subject'].values[0]
            if s not in subjects_in_map: subjects_in_map.append(s)
            
        subj_idx = subjects_in_map.index(current_subj) if current_subj in subjects_in_map else 0
        selected_subj = st.radio("Subject Filter", subjects_in_map, index=subj_idx, horizontal=True, label_visibility="collapsed")
        st.markdown("---")
        
        subj_q_ids = [qid for qid in st.session_state.q_map if df_questions.loc[df_questions['id'] == qid, 'subject'].values[0] == selected_subj]
        types_in_subj = []
        for qid in subj_q_ids:
            t = df_questions.loc[df_questions['id'] == qid, 'question_type'].values[0]
            if t not in types_in_subj: types_in_subj.append(t)
            
        for q_type in types_in_subj:
            st.caption(f"**{q_type}**")
            type_q_ids = [qid for qid in subj_q_ids if df_questions.loc[df_questions['id'] == qid, 'question_type'].values[0] == q_type]
            cols = st.columns(4)
            for col_idx, qid in enumerate(type_q_ids):
                exam_q_num = st.session_state.q_map.index(qid)
                status = st.session_state.status.get(qid, 'not_visited')
                emoji = {'not_visited': '⚪', 'not_answered': '🔴', 'answered': '🟢', 'review': '🟣', 'ans_review': '🟣✅'}.get(status, '⚪')
                btn_style = 'primary' if exam_q_num == st.session_state.current_idx else 'secondary'
                if cols[col_idx % 4].button(f"{emoji} {exam_q_num+1}", key=f"nav_{qid}", type=btn_style):
                    update_timer(); mark_visited(); st.session_state.current_idx = exam_q_num; st.rerun()

    with col_q:
        q_id = st.session_state.q_map[st.session_state.current_idx]
        q = df_questions[df_questions['id'] == q_id].iloc[0]
        st.markdown(f'<div class="jee-card"><div style="display:flex; justify-content:space-between;"><h3>Q{st.session_state.current_idx+1} ({q["question_type"]})</h3><span style="color:gray;">DB Ref: #{q_id}</span></div><p>{q["question_text"]}</p></div>', unsafe_allow_html=True)
        if q['question_img']: st.image(q['question_img'])
        
        if any([q['option_a_img'], q['option_b_img']]):
            c1, c2 = st.columns(2)
            with c1:
                if q['option_a_img']: st.image(q['option_a_img'], caption="A")
                if q['option_c_img']: st.image(q['option_c_img'], caption="C")
            with c2:
                if q['option_b_img']: st.image(q['option_b_img'], caption="B")
                if q['option_d_img']: st.image(q['option_d_img'], caption="D")

        ans = st.session_state.responses.get(q_id, "")
        if q['question_type'] == "Multi-Correct":
            curr = ans.split(",") if ans else []
            c1, c2, c3, c4 = st.columns(4)
            a = c1.checkbox("A", "A" in curr, key=f"ca_{q_id}"); b = c2.checkbox("B", "B" in curr, key=f"cb_{q_id}")
            c = c3.checkbox("C", "C" in curr, key=f"cc_{q_id}"); d = c4.checkbox("D", "D" in curr, key=f"cd_{q_id}")
            val = ",".join([i for i, j in zip("ABCD", [a,b,c,d]) if j])
        elif q['question_type'] in ["Numerical", "Integer"]:
            val = st.text_input("Value:", value=ans, key=f"ti_{q_id}")
        else:
            r_idx = ["A","B","C","D"].index(ans) if ans in ["A","B","C","D"] else None
            val = st.radio("Options:", ["A","B","C","D"], index=r_idx, key=f"ra_{q_id}")
        
        ac1, ac2, ac3 = st.columns(3)
        if ac1.button("Save & Next"):
            update_timer(); st.session_state.responses[q_id] = val; st.session_state.status[q_id] = 'answered' if val else 'not_answered'
            if st.session_state.current_idx < len(st.session_state.q_map)-1: 
                st.session_state.current_idx += 1; st.rerun()
            else: change_phase('summary') 
            
        if ac2.button("Clear Response"):
            if q_id in st.session_state.responses: del st.session_state.responses[q_id]
            st.session_state.status[q_id] = 'not_answered'; st.rerun()
            
        if ac3.button("Mark Review"):
            update_timer(); st.session_state.responses[q_id] = val; st.session_state.status[q_id] = 'ans_review' if val else 'review'
            if st.session_state.current_idx < len(st.session_state.q_map)-1: 
                st.session_state.current_idx += 1; st.rerun()
            else: change_phase('summary')


# --- CHUNK 5.5: EDITORS, ANALYTICS & PARENT DB ---
def question_editor():
    st.header("🛠️ Pre-Test Editor")
    if not st.session_state.selected_paper: st.warning("Select a paper on Home screen."); return
    conn = sqlite3.connect(st.session_state.selected_paper)
    df = pd.read_sql("SELECT id, subject, chapter, question_type, marks_pos, marks_neg, correct_option FROM questions", conn)
    edited = st.data_editor(df, use_container_width=True, hide_index=True,
        column_config={
            "subject": st.column_config.SelectboxColumn("Subject", options=["Physics", "Chemistry", "Mathematics"], required=True),
            "question_type": st.column_config.SelectboxColumn("Type", options=["Single Correct", "Multi-Correct", "Paragraph", "Integer", "Numerical"], required=True)
        })
    if st.button("Save Changes", type="primary"):
        c = conn.cursor()
        for _, r in edited.iterrows():
            c.execute("UPDATE questions SET subject=?, chapter=?, question_type=?, marks_pos=?, marks_neg=?, correct_option=? WHERE id=?", 
                      (r['subject'], r['chapter'], r['question_type'], r['marks_pos'], r['marks_neg'], r['correct_option'], r['id']))
        conn.commit(); st.success("Updated Successfully!"); st.rerun()
    conn.close()

def render_review_browser():
    st.title("📖 Paper Review Mode")
    st.info("Study your attempt. You can categorize your mistakes here anytime.")
    
    if st.button("⬅️ Back to Analytics"): change_phase('analytics')
    
    conn = sqlite3.connect(st.session_state.selected_paper)
    df = pd.read_sql("SELECT r.id as rid, r.user_answer, r.is_correct, r.score_awarded, r.time_taken_sec, r.category, q.* FROM responses r JOIN questions q ON r.question_id = q.id", conn)
    
    if df.empty:
        st.warning("No attempts found for this paper."); conn.close(); return
        
    if 'rev_idx' not in st.session_state: st.session_state.rev_idx = 0
    
    c1, c2, c3 = st.columns([1, 2, 1])
    if c1.button("Previous Question") and st.session_state.rev_idx > 0:
        st.session_state.rev_idx -= 1; st.rerun()
    if c3.button("Next Question") and st.session_state.rev_idx < len(df) - 1:
        st.session_state.rev_idx += 1; st.rerun()

    r = df.iloc[st.session_state.rev_idx]
    
    status_col = "#28a745" if r['is_correct'] else "#dc3545"
    if not r['user_answer']: status_col = "#6c757d"
    st.markdown(f"""
    <div style="background-color: {status_col}; color: white; padding: 10px; border-radius: 5px; margin-bottom: 15px;">
        <strong>Q{st.session_state.rev_idx + 1} ({r['subject']} - {r['chapter']})</strong> | 
        Score: {r['score_awarded']} | Time Spent: {r['time_taken_sec']}s
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown(f'<div class="jee-card"><p>{r["question_text"]}</p></div>', unsafe_allow_html=True)
    if r['question_img']: st.image(r['question_img'])
    
    if any([r['option_a_img'], r['option_b_img']]):
        col_a, col_b = st.columns(2)
        with col_a:
            if r['option_a_img']: st.image(r['option_a_img'], caption="A")
            if r['option_c_img']: st.image(r['option_c_img'], caption="C")
        with col_b:
            if r['option_b_img']: st.image(r['option_b_img'], caption="B")
            if r['option_d_img']: st.image(r['option_d_img'], caption="D")
    
    c_ans, c_key = st.columns(2)
    c_ans.metric("Your Answer", r['user_answer'] if r['user_answer'] else "Skipped")
    c_key.metric("Official Key", r['correct_option'])
    
    st.markdown("---")
    st.write("### Tag Error Category")
    options = ["Pending Review", "Perfect", "Silly Mistake", "Conceptual Error", "Time Pressure", "Skipped", "Guessed"]
    current_cat = r['category'] if r['category'] in options else "Pending Review"
    
    new_cat = st.selectbox("Update Mistake Type:", options, index=options.index(current_cat), key=f"rev_cat_{r['rid']}")
    if st.button("Save Tag", type="primary"):
        c = conn.cursor()
        c.execute("UPDATE responses SET category=? WHERE id=?", (new_cat, r['rid']))
        conn.commit(); st.success("Tag Saved!"); time.sleep(0.5); st.rerun()
        
    conn.close()

def analytics_dashboard():
    st.title("📊 Test Analytics")
    papers = get_available_papers()
    if not papers: return
    target_db = st.selectbox("Select Paper to Analyze:", papers, format_func=lambda x: os.path.basename(x).replace('.db', ''))
    
    if st.button("📖 Browse & Review Paper (Categorize Mistakes)", type="primary"):
        st.session_state.selected_paper = target_db
        st.session_state.rev_idx = 0
        change_phase('review_paper')

    st.markdown("---")
    if st.button("✨ Aclaim Results (Upload to Parent DB)", type="secondary"):
        if aclaim_to_parent(target_db): st.balloons(); st.success("Merged into All Time Analytics!")
        else: st.error("No analyzed results found to aclaim.")
    st.markdown("---")

    conn = sqlite3.connect(target_db)
    df = pd.read_sql("""SELECT r.category as Category, r.score_awarded as Score, r.time_taken_sec, r.is_correct, r.user_answer, q.chapter as Chapter 
                        FROM responses r JOIN questions q ON r.question_id = q.id WHERE r.manual_review_done = 1""", conn)
    conn.close()
    if df.empty: st.info("No attempts recorded for this paper yet."); return

    df['Result'] = df.apply(lambda row: 'Skipped' if not row['user_answer'] else ('Correct' if row['is_correct'] else 'Incorrect'), axis=1)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Score", df['Score'].sum())
    m2.metric("Attempted", len(df[df['Result'] != 'Skipped']))
    m3.metric("Correct", len(df[df['Result'] == 'Correct']))
    m4.metric("Avg Time / Q", f"{df['time_taken_sec'].mean():.1f}s")

    c1, c2 = st.columns(2)
    with c1:
        fig1 = px.pie(df, names='Result', title="Accuracy Breakdown", hole=0.4, 
                      color='Result', color_discrete_map={'Correct':'#28a745', 'Incorrect':'#dc3545', 'Skipped':'#6c757d'})
        st.plotly_chart(fig1, use_container_width=True)
    with c2:
        fig2 = px.pie(df[df['Category'] != 'Pending Review'], names='Category', title="Mistake Analysis (Tagged)", hole=0.4)
        st.plotly_chart(fig2, use_container_width=True)

    # UPDATED: Clean Dot Plot (Strip Chart) for Time vs Chapter
    st.markdown("---")
    if not df['Chapter'].empty:
        df_time = df[df['Result'] != 'Skipped']
        if not df_time.empty:
            fig3 = px.strip(df_time, x='Chapter', y='time_taken_sec', 
                            title="Time Taken per Question (Seconds)",
                            labels={'time_taken_sec': 'Time Taken (Seconds)', 'Chapter': 'Chapter'})
            
            # Make the dots slightly larger so they are easy to see
            fig3.update_traces(marker=dict(size=8, opacity=0.7, color="#4A90E2"))
            st.plotly_chart(fig3, use_container_width=True)

def render_parent_stats():
    st.title("🌐 All Time Analytics")
    
    # Use the dynamic path function instead of the old constant
    user_parent_path = get_parent_db_path()
    
    with st.expander("⚠️ Danger Zone: Clear All Time Analytics"):
        if st.button("Delete Parent Database"):
            if os.path.exists(user_parent_path):
                os.remove(user_parent_path)
                st.success("Wiped clean!")
                time.sleep(1)
                st.rerun()
    
    if not os.path.exists(user_parent_path): 
        st.info("No Data. 'Aclaim' some results first!")
        return
    conn = sqlite3.connect(user_parent_path)
    df = pd.read_sql("SELECT * FROM chapter_stats", conn)
    conn.close()
    if df.empty: st.info("All time Database is empty."); return
    
    if 'subject' not in df.columns:
        st.warning("Please expand the 'Danger Zone' above and 'Delete Parent Database', then re-Aclaim your results to enable the Subject Filter!")
        return
        
    subjects = ["All"] + sorted(df['subject'].dropna().unique().tolist())
    selected_subj = st.selectbox("Filter by Subject:", subjects)
    
    if selected_subj != "All":
        df = df[df['subject'] == selected_subj]
        
    if df.empty:
        st.info(f"No data available for {selected_subj}.")
        return
        
    df['Accuracy (%)'] = (df['correct'] / df['total_attempted'] * 100).round(1)
    df['Avg Time (s)'] = (df['total_time_sec'] / df['total_attempted']).round(1)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Qs Attempted", df['total_attempted'].sum())
    c2.metric("Filtered Accuracy", f"{(df['correct'].sum() / df['total_attempted'].sum() * 100):.1f}%")
    c3.metric("Strongest Chapter", df.loc[df['Accuracy (%)'].idxmax(), 'chapter'] if not df.empty else "N/A")

    st.markdown("---")
    st.subheader("Quadrant Analysis: Speed vs. Accuracy")
    st.info("Top Left = Fast & Accurate (Mastered). Bottom Right = Slow & Inaccurate (Needs Work).")
    
    df['Speed Rating'] = df['Avg Time (s)'].max() - df['Avg Time (s)'] 
    
    fig_quad = px.scatter(df, x='Accuracy (%)', y='Speed Rating', text='chapter', size='total_attempted',
                          color='Accuracy (%)', color_continuous_scale='RdYlGn',
                          labels={'Speed Rating': 'Speed (Higher is Faster)', 'Accuracy (%)': 'Accuracy (%)'})
    fig_quad.update_traces(textposition='top center')
    
    acc_mean = df['Accuracy (%)'].mean() if len(df) > 0 else 50
    spd_mean = df['Speed Rating'].mean() if len(df) > 0 else 0
    
    fig_quad.add_vline(x=acc_mean, line_width=2, line_dash="dash", line_color="gray")
    fig_quad.add_hline(y=spd_mean, line_width=2, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_quad, use_container_width=True)

    display_df = df[['chapter', 'subject', 'total_attempted', 'correct', 'incorrect', 'Accuracy (%)', 'Avg Time (s)']]
    display_df.columns = ['Chapter', 'Subject', 'Attempted', 'Correct', 'Incorrect', 'Accuracy (%)', 'Avg Time / Q (s)']
    st.dataframe(display_df.sort_values(by='Accuracy (%)', ascending=False), use_container_width=True, hide_index=True)



# --- CHUNK 6: MAIN EXECUTION ---
def main():
    if st.session_state.app_phase == 'login':
        render_login()
        return # Block all other execution until logged in

    # If logged in, show sidebar (except during test/review)
    if st.session_state.app_phase not in ['test', 'summary', 'review_paper']:
        with st.sidebar:
            st.title(f"👤 {st.session_state.username}")
            if st.button("Logout", use_container_width=True):
                st.session_state.clear()
                st.rerun()
                
            st.markdown("---")
            nav = st.radio("Navigation:", ["Home", "Edit Questions (Pre-Test)", "Test Analytics", "All Time Analytics"])
            
            st.markdown("---")
            with st.expander("⚠️ Danger Zone"):
                if st.button("Reset Attempts (Retake Paper)"):
                    if st.session_state.selected_paper and os.path.exists(st.session_state.selected_paper): 
                        conn = sqlite3.connect(st.session_state.selected_paper)
                        conn.execute("DELETE FROM responses")
                        conn.commit(); conn.close()
                        st.session_state.responses = {}; st.session_state.status = {}; st.session_state.timers = {}
                        st.success("Test history cleared!"); time.sleep(1); change_phase('home')

            if nav == "Home" and st.session_state.app_phase not in ['home', 'instructions']: change_phase('home')
            elif nav == "Test Analytics" and st.session_state.app_phase != 'analytics': change_phase('analytics')
            elif nav == "Edit Questions (Pre-Test)" and st.session_state.app_phase != 'editor': change_phase('editor')
            elif nav == "All Time Analytics" and st.session_state.app_phase != 'parent_db': change_phase('parent_db')

    # Routing
    if st.session_state.app_phase == 'home': render_home()
    elif st.session_state.app_phase == 'instructions': render_instructions()
    elif st.session_state.app_phase == 'test': render_test_interface()
    elif st.session_state.app_phase == 'summary': render_summary()
    elif st.session_state.app_phase == 'review_paper': render_review_browser()
    elif st.session_state.app_phase == 'analytics': analytics_dashboard()
    elif st.session_state.app_phase == 'editor': question_editor()
    elif st.session_state.app_phase == 'parent_db': render_parent_stats()

# Minor fix for render_parent_stats in Chunk 5.5 to use the dynamic path:
# Replace os.path.exists(PARENT_DB) with os.path.exists(get_parent_db_path()) in that function.

if __name__ == "__main__":
    main()
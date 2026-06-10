import streamlit as st
import sqlite3
import datetime
from openai import OpenAI
from dotenv import load_dotenv
import os
import pdfplumber
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import pythoncom
pythoncom.CoInitialize()

from docx import Document
from docx2pdf import convert
import pandas as pd
import tempfile
from PyPDF2 import PdfReader

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def init_db():
    conn = sqlite3.connect("resume_history.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            original TEXT,
            job_description TEXT,
            tailored TEXT
        )
    ''')
    conn.commit()
    return conn

def store_resume(conn, original, jd, tailored):
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO resumes (timestamp, original, job_description, tailored)
        VALUES (?, ?, ?, ?)
    ''', (datetime.datetime.now(), original, jd, tailored))
    conn.commit()

def extract_text(file):
    filename = file.name.lower()
    
    if filename.endswith(".pdf"):
        with pdfplumber.open(file) as pdf:
            return "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
    
    elif filename.endswith(".docx"):
        doc = Document(file)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    
    elif filename.endswith(".doc"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".doc") as tmp:
            tmp.write(file.read())
            tmp.flush()
            new_docx = tmp.name + "x"
            os.system(f'soffice --headless --convert-to docx "{tmp.name}" --outdir "{os.path.dirname(tmp.name)}"')
            doc = Document(new_docx)
            os.remove(tmp.name)
            os.remove(new_docx)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    
    elif filename.endswith(".txt"):
        return file.read().decode("utf-8")
    
    else:
        return ""

def calculate_match_score(text1, text2):
    vectorizer = CountVectorizer().fit_transform([text1, text2])
    vectors = vectorizer.toarray()
    return round(cosine_similarity([vectors[0]], [vectors[1]])[0][0] * 100, 2)

def analyze_alignment(text, jd_text):
    soft_skills = ["communication", "leadership", "teamwork", "adaptability", "empathy"]
    tech_skills = ["python", "machine learning", "aws", "gcp", "tensorflow", "pytorch", "docker", "kubernetes"]
    soft_score = sum(skill in text.lower() for skill in soft_skills)
    tech_score = sum(skill in text.lower() for skill in tech_skills)
    
    def score_to_level(score):
        if score >= 4: return "High"
        elif score >= 2: return "Moderate"
        else: return "Low"
    
    return score_to_level(soft_score), score_to_level(tech_score)

def estimate_length(text):
    words = text.split()
    words_per_page = 350
    pages = max(1, round(len(words) / words_per_page))
    return f"{pages} page{'s' if pages > 1 else ''}"

def generate_resume(profile_text, job_description):
    prompt = f"""
You are a professional resume writer. Rewrite the given resume/profile to align with the job description as closely as possible without exaggeration.

Important Instructions:
- Retain all relevant technical skills and keywords present in the original resume, even if they are not explicitly mentioned in the job description.
- Emphasize skills and experience relevant to the job description.
- Do not remove technical content from the original resume unless it is completely irrelevant to the role.

### Resume/Profile:
{profile_text}

### Job Description:
{job_description}

### Tailored Resume:
"""
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=1500
    )
    return response.choices[0].message.content


def generate_pdf_from_docx(text, pdf_filename="Tailored_Resume.pdf"):
    docx_file = "temp_resume.docx"
    doc = Document()
    for line in text.split('\n'):
        doc.add_paragraph(line)
    doc.save(docx_file)
    
    convert(docx_file, pdf_filename)
    os.remove(docx_file)
    
    reader = PdfReader(pdf_filename)
    actual_pages = len(reader.pages)
    
    return pdf_filename, actual_pages

# Streamlit UI
st.set_page_config(page_title="AI-Powered Resume Assistant", layout="wide")
st.title("🧠 AI-Powered Resume Assistant")
st.markdown("Upload your resume and job description to generate a tailored version with match score.")

uploaded_resume = st.file_uploader("📄 Upload Resume (PDF, DOC, DOCX, TXT)", type=['pdf', 'doc', 'docx', 'txt'])
uploaded_jd = st.file_uploader("📑 Upload Job Description (PDF, DOC, DOCX, TXT)", type=['pdf', 'doc', 'docx', 'txt'])

if uploaded_resume and uploaded_jd:
    profile_text = extract_text(uploaded_resume)
    jd_text = extract_text(uploaded_jd)

    if not profile_text or not jd_text:
        st.error("Failed to extract text from one of the files. Please check the file format and content.")
    else:
        before_score = calculate_match_score(profile_text, jd_text)
        st.subheader("📊 Before Optimization")
        st.metric("JD Match Score", f"{before_score}%")

        if st.button("🚀 Generate Tailored Resume"):
            with st.spinner("Generating tailored resume..."):
                tailored_resume = generate_resume(profile_text, jd_text)
                
                after_score = calculate_match_score(tailored_resume, jd_text)
                before_soft, before_tech = analyze_alignment(profile_text, jd_text)
                after_soft, after_tech = analyze_alignment(tailored_resume, jd_text)
                
                before_len = estimate_length(profile_text)
                
                pdf_file, actual_pages = generate_pdf_from_docx(tailored_resume)
                
                st.subheader("📊 1. Matrices Before vs After Optimization")
                metrics = {
                    "JD Keywords Matched": [f"{before_score}%", f"{after_score}%"],
                    "Soft Skills Alignment": [before_soft, after_soft],
                    "Technical Keywords Matched": [before_tech, after_tech],
                    "Resume Length": [before_len, f"{actual_pages} page{'s' if actual_pages > 1 else ''} (Actual)"]
                }
                df = pd.DataFrame(metrics, index=["Before Optimization", "After Optimization"]).T
                st.table(df)

                st.subheader("📝 Tailored Resume Preview")
                st.text_area("Resume Content", tailored_resume, height=400)

                conn = init_db()
                store_resume(conn, profile_text, jd_text, tailored_resume)

                with open(pdf_file, "rb") as f:
                    st.download_button("⬇️ Download Tailored Resume (PDF)", f, file_name="Tailored_Resume.pdf")
                os.remove(pdf_file)

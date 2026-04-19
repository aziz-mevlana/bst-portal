import PyPDF2
import io


def extract_text_from_pdf(pdf_file):
    """PDF dosyasindan metin cikar"""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        return f"PDF okuma hatasi: {str(e)}"


def extract_text_from_pdf_path(pdf_path):
    """PDF dosya yolundan metin cikar"""
    try:
        with open(pdf_path, 'rb') as f:
            return extract_text_from_pdf(f)
    except Exception as e:
        return f"PDF okuma hatasi: {str(e)}"

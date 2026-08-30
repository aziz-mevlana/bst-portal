import PyPDF2


def extract_text_from_pdf(pdf_file):
    """PDF dosyasindan metin cikar"""
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    if pdf_reader.is_encrypted:
        raise ValueError('Şifreli PDF dosyaları desteklenmiyor.')
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text() or ""
    if not text.strip():
        raise ValueError('PDF içinden okunabilir metin çıkarılamadı.')
    return text


def extract_text_from_pdf_path(pdf_path):
    """PDF dosya yolundan metin cikar"""
    with open(pdf_path, 'rb') as f:
        return extract_text_from_pdf(f)

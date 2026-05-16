"""
pdf_engine.py
=============
SafeTrade AI Raporlarını kurumsal PDF formatına dönüştüren asenkron servis.
"""

from typing import List, Dict, Tuple, Optional, Union, Any
import os
import asyncio
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Türkçe karakter desteği için font kaydetmeyi deneriz.
# Standart Helvetica Türkçe karakterleri tam desteklemez.
try:
    if os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        pdfmetrics.registerFont(TTFont('TRFont', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('TRFont-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
    elif os.path.exists("C:\\Windows\\Fonts\\arial.ttf"):
        pdfmetrics.registerFont(TTFont('TRFont', 'C:\\Windows\\Fonts\\arial.ttf'))
        pdfmetrics.registerFont(TTFont('TRFont-Bold', 'C:\\Windows\\Fonts\\arialbd.ttf'))
    elif os.path.exists("/usr/share/fonts/truetype/freefont/FreeSans.ttf"):
        pdfmetrics.registerFont(TTFont('TRFont', '/usr/share/fonts/truetype/freefont/FreeSans.ttf'))
        pdfmetrics.registerFont(TTFont('TRFont-Bold', '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf'))
    else:
        pass
except Exception:
    pass

def get_font(is_bold=False):
    if 'TRFont' in pdfmetrics.getRegisteredFontNames():
        return 'TRFont-Bold' if is_bold and 'TRFont-Bold' in pdfmetrics.getRegisteredFontNames() else 'TRFont'
    return 'Helvetica-Bold' if is_bold else 'Helvetica'

class PDFService:
    @staticmethod
    async def generate_report_pdf(
        company_name: str, 
        score: int, 
        detailed_scores: dict,
        summary: str, 
        risk_level: str, 
        output_dir: str = "reports"
    ) -> str:
        """
        AI raporunu kurumsal bir PDF dosyasına dönüştürür.
        Bloklamayı önlemek için CPU-bound olan PDF üretimini ayrı bir thread'de çalıştırır.
        """
        
        # Raporların kaydedileceği dizini oluştur
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_company_name = "".join(c if c.isalnum() else "_" for c in company_name)
        output_path = os.path.join(output_dir, f"{safe_company_name}_Report_{timestamp}.pdf")

        def build_pdf():
            doc = SimpleDocTemplate(
                output_path, 
                pagesize=A4, 
                rightMargin=40, 
                leftMargin=40, 
                topMargin=40, 
                bottomMargin=18
            )
            styles = getSampleStyleSheet()
            
            # Kurumsal Renk Paleti ve Stiller
            title_style = ParagraphStyle(
                name="CustomTitle",
                parent=styles["Heading1"],
                fontSize=22,
                textColor=colors.HexColor("#1A237E"),
                spaceAfter=20,
                alignment=1 # Center
            )
            
            subtitle_style = ParagraphStyle(
                name="CustomSubtitle",
                parent=styles["Heading2"],
                fontSize=14,
                fontName=get_font(is_bold=True),
                textColor=colors.HexColor("#424242"),
                spaceAfter=30,
                alignment=1 # Center
            )
            
            normal_style = styles["Normal"]
            normal_style.fontName = get_font()
            normal_style.fontSize = 11
            normal_style.leading = 16
            
            elements = []
            
            # Başlık
            elements.append(Paragraph("SafeTrade AI - Istihbarat Raporu", title_style))
            elements.append(Paragraph(f"Sirket: {company_name}", subtitle_style))
            
            # Tarih
            date_str = datetime.now().strftime("%d %B %Y - %H:%M")
            elements.append(Paragraph(f"<b>Olusturulma Tarihi:</b> {date_str}", normal_style))
            elements.append(Spacer(1, 20))
            
            # Riske göre renk belirleme
            risk_color = colors.HexColor("#4CAF50") # Green for Low
            if risk_level.lower() == "medium":
                risk_color = colors.HexColor("#FF9800") # Orange
            elif risk_level.lower() == "high":
                risk_color = colors.HexColor("#F44336") # Red
            
            # Özet Tablosu
            data = [
                ["Analiz Metriği", "Skor / Değer"],
                ["Genel Güven Skoru", f"%{score}"],
                ["Müşteri Memnuniyeti Skoru", f"%{detailed_scores.get('musteri_memnuniyeti_skoru', 0)}"],
                ["Kalite Skoru", f"%{detailed_scores.get('kalite_skoru', 0)}"],
                ["Operasyon ve Yönetişim Skoru", f"%{detailed_scores.get('operasyon_ve_yonetisim_skoru', 0)}"],
                ["Risk Seviyesi", risk_level]
            ]
            
            t = Table(data, colWidths=[200, 250])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A237E")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), get_font(is_bold=True)),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('TOPPADDING', (0, 0), (-1, 0), 10),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#F8F9FA")),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor("#212121")),
                ('TEXTCOLOR', (1, -1), (1, -1), risk_color), # Sadece son satırdaki risk rengi
                ('FONTNAME', (0, 1), (-1, -1), get_font()),
                ('FONTNAME', (1, 1), (1, -1), get_font(is_bold=True)),
                ('FONTSIZE', (0, 1), (-1, -1), 11),
                ('PADDING', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#E0E0E0"))
            ]))
            elements.append(t)
            elements.append(Spacer(1, 30))
            
            # AI Yonetici Ozeti
            heading3_style = styles["Heading3"]
            heading3_style.fontName = get_font(is_bold=True)
            elements.append(Paragraph("<b>AI Yönetici Özeti</b>", heading3_style))
            elements.append(Spacer(1, 10))
            
            # Eğer özel font yüklenemediyse TR karakterleri dönüştür
            if 'TRFont' not in pdfmetrics.getRegisteredFontNames():
                tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
                safe_summary = summary.translate(tr_map)
            else:
                safe_summary = summary
            
            elements.append(Paragraph(safe_summary, normal_style))
            
            # Footer
            elements.append(Spacer(1, 60))
            footer_style = ParagraphStyle(
                name="Footer",
                parent=styles["Italic"],
                fontSize=9,
                fontName=get_font(),
                textColor=colors.gray,
                alignment=1
            )
            elements.append(Paragraph("Bu rapor SafeTrade AI tarafından otomatik olarak üretilmiştir.", footer_style))
            
            doc.build(elements)
            return output_path
            
        return await asyncio.to_thread(build_pdf)

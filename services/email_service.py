"""
email_service.py — Resend API ile HTML email gönderme servisi

SafeTrade AI aylık pazar raporu alertlerini HTML formatında gönderir.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _score_color(score: int) -> str:
    """Skora göre renk kodu döner."""
    if score >= 75:
        return "#10b981"  # yeşil
    elif score >= 50:
        return "#f59e0b"  # sarı/turuncu
    return "#ef4444"  # kırmızı


def _score_label(score: int) -> str:
    if score >= 75:
        return "Güçlü"
    elif score >= 50:
        return "Orta"
    return "Zayıf"


def _render_list(items: list, bullet_color: str) -> str:
    """HTML <li> listesi oluşturur."""
    if not items:
        return "<li style='color:#94a3b8'>Veri bulunamadı</li>"
    return "".join(
        f"<li style='margin-bottom:6px'>"
        f"<span style='color:{bullet_color};margin-right:8px'>●</span>"
        f"{item}</li>"
        for item in items[:5]
    )


def build_market_report_html(
    company_name: str,
    analysis: dict,
    alert_id: int,
    frontend_base_url: str,
) -> str:
    """Pazar analizi raporunu şık HTML template'e dönüştürür."""
    score = int(analysis.get("pazar_algisi_skoru", 0))
    score_color = _score_color(score)
    score_label = _score_label(score)
    stratejik_ozet = analysis.get("stratejik_ozet", "Özet oluşturulamadı.")
    guclu_yonler = analysis.get("guclu_yonler", [])
    zayif_yonler = analysis.get("zayif_yonler", [])
    ne_yapmali = analysis.get("ne_yapmali", [])
    unsubscribe_url = f"{frontend_base_url}/alerts/{alert_id}/unsubscribe"

    guclu_html = _render_list(guclu_yonler, "#10b981")
    zayif_html = _render_list(zayif_yonler, "#ef4444")
    yapmali_html = _render_list(ne_yapmali, "#3b82f6")

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>SafeTrade AI — Aylık Pazar Raporu</title>
</head>
<body style="margin:0;padding:0;background:#0b0c15;font-family:'Segoe UI',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0b0c15;min-height:100vh">
    <tr>
      <td align="center" style="padding:40px 20px">
        <table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%">

          <!-- HEADER -->
          <tr>
            <td style="background:linear-gradient(135deg,#7c3aed,#a78bfa);border-radius:20px 20px 0 0;padding:32px 40px;text-align:center">
              <div style="font-size:28px;margin-bottom:4px">🛡️</div>
              <div style="color:white;font-size:22px;font-weight:800;letter-spacing:1px">SafeTrade <span style="opacity:0.85">AI</span></div>
              <div style="color:rgba(255,255,255,0.75);font-size:13px;margin-top:6px">Aylık Otomatik Pazar Raporu</div>
            </td>
          </tr>

          <!-- BODY -->
          <tr>
            <td style="background:#13141f;border:1px solid rgba(255,255,255,0.06);border-top:none;border-radius:0 0 20px 20px;padding:40px">

              <!-- Şirket adı -->
              <h1 style="margin:0 0 6px;color:white;font-size:24px;font-weight:800">{company_name}</h1>
              <p style="margin:0 0 32px;color:#64748b;font-size:13px">Pazar analizi hazırlandı · SafeTrade AI</p>

              <!-- SKOR KUTUSU -->
              <table width="100%" cellpadding="0" cellspacing="0" style="background:rgba(124,58,237,0.08);border:1px solid rgba(124,58,237,0.25);border-radius:16px;margin-bottom:28px">
                <tr>
                  <td style="padding:28px 32px">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding-right:28px;vertical-align:middle">
                          <div style="width:90px;height:90px;border-radius:50%;background:conic-gradient({score_color} {score}%,rgba(255,255,255,0.05) 0);display:flex;align-items:center;justify-content:center;position:relative">
                            <div style="width:70px;height:70px;border-radius:50%;background:#13141f;position:absolute;top:10px;left:10px;display:flex;flex-direction:column;align-items:center;justify-content:center">
                              <span style="color:{score_color};font-size:22px;font-weight:900;line-height:1">{score}</span>
                              <span style="color:#64748b;font-size:10px">/100</span>
                            </div>
                          </div>
                        </td>
                        <td style="vertical-align:middle">
                          <div style="color:#94a3b8;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Pazar Algı Skoru</div>
                          <div style="color:{score_color};font-size:26px;font-weight:900;margin-bottom:4px">{score_label}</div>
                          <div style="color:#64748b;font-size:12px">{score}/100 puan aldı</div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- STRATEJİK ÖZET -->
              <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:14px;padding:22px;margin-bottom:24px">
                <div style="color:#a78bfa;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">📊 Stratejik Özet</div>
                <p style="color:#cbd5e1;font-size:14px;line-height:1.7;margin:0">{stratejik_ozet}</p>
              </div>

              <!-- 3 KOLON -->
              <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px">
                <tr>
                  <td width="33%" style="padding-right:8px;vertical-align:top">
                    <div style="background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.2);border-radius:14px;padding:18px">
                      <div style="color:#10b981;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">💪 Güçlü Yönler</div>
                      <ul style="margin:0;padding:0;list-style:none;color:#94a3b8;font-size:13px">
                        {guclu_html}
                      </ul>
                    </div>
                  </td>
                  <td width="33%" style="padding:0 4px;vertical-align:top">
                    <div style="background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);border-radius:14px;padding:18px">
                      <div style="color:#ef4444;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">⚠️ Zayıf Yönler</div>
                      <ul style="margin:0;padding:0;list-style:none;color:#94a3b8;font-size:13px">
                        {zayif_html}
                      </ul>
                    </div>
                  </td>
                  <td width="34%" style="padding-left:8px;vertical-align:top">
                    <div style="background:rgba(59,130,246,0.06);border:1px solid rgba(59,130,246,0.2);border-radius:14px;padding:18px">
                      <div style="color:#3b82f6;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">✅ Ne Yapmalı</div>
                      <ul style="margin:0;padding:0;list-style:none;color:#94a3b8;font-size:13px">
                        {yapmali_html}
                      </ul>
                    </div>
                  </td>
                </tr>
              </table>

              <!-- FOOTER / UNSUBSCRIBE -->
              <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid rgba(255,255,255,0.06);padding-top:24px;margin-top:8px">
                <tr>
                  <td align="center">
                    <p style="color:#475569;font-size:12px;line-height:1.6;margin:0 0 12px">
                      Bu rapor SafeTrade AI tarafından otomatik olarak hazırlanmıştır.<br>
                      Her ay bu şirket için güncel pazar raporu e-postanıza iletilecektir.
                    </p>
                    <a href="{unsubscribe_url}"
                       style="display:inline-block;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#ef4444;text-decoration:none;font-size:12px;font-weight:600;padding:8px 20px;border-radius:8px">
                      🔕 Bu raporu durdurmak için tıklayın
                    </a>
                    <p style="color:#334155;font-size:11px;margin:16px 0 0">
                      © 2026 SafeTrade AI — Tüm hakları saklıdır.
                    </p>
                  </td>
                </tr>
              </table>

            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


class EmailService:
    """
    Resend API ile email gönderme servisi.

    Kullanım:
        svc = EmailService()
        await svc.send_market_report(
            to_email="user@example.com",
            company_name="Acme A.Ş.",
            analysis_data={...},
            alert_id=42,
        )
    """

    FROM_EMAIL = "onboarding@resend.dev"
    FROM_NAME = "SafeTrade AI"

    def __init__(self) -> None:
        from app.config import get_settings
        self._settings = get_settings()

    async def send_market_report(
        self,
        to_email: str,
        company_name: str,
        analysis_data: dict,
        alert_id: int,
    ) -> bool:
        """
        Kullanıcıya aylık pazar raporu gönderir.

        Returns:
            True → başarılı, False → API anahtarı yok veya hata
        """
        if not self._settings.resend_api_key:
            logger.warning(
                "RESEND_API_KEY ayarlanmamış, email atlanıyor. "
                "alert_id=%s to=%s", alert_id, to_email
            )
            return False

        import resend  # geç import — paket opsiyonel

        resend.api_key = self._settings.resend_api_key

        subject = (
            f"[SafeTrade AI] {company_name} — Aylık Pazar Raporu"
        )
        html_body = build_market_report_html(
            company_name=company_name,
            analysis=analysis_data,
            alert_id=alert_id,
            frontend_base_url=self._settings.frontend_base_url,
        )

        try:
            params: resend.Emails.SendParams = {
                "from": f"{self.FROM_NAME} <{self.FROM_EMAIL}>",
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            }
            resp = resend.Emails.send(params)
            email_id = resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)
            logger.info(
                "Email gönderildi. alert_id=%s to=%s resend_id=%s",
                alert_id, to_email, email_id,
            )
            return True
        except Exception as exc:
            logger.error(
                "Email gönderilemedi. alert_id=%s to=%s hata=%s",
                alert_id, to_email, exc,
            )
            return False

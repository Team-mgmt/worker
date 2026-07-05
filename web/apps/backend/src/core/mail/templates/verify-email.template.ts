export interface VerifyEmailTemplateParams {
  name: string;
  verifyUrl: string;
  expiresInHours: number;
}

export function renderVerifyEmailTemplate({
  name,
  verifyUrl,
  expiresInHours,
}: VerifyEmailTemplateParams) {
  const subject = "[ShelfAlign] 이메일 인증을 완료해주세요";
  const text = [
    `${name}님, 안녕하세요.`,
    "",
    "아래 링크를 눌러 이메일 인증을 완료해주세요.",
    verifyUrl,
    "",
    `이 링크는 ${expiresInHours}시간 동안 유효합니다.`,
  ].join("\n");
  const html = `
    <p>${escapeHtml(name)}님, 안녕하세요.</p>
    <p>아래 버튼을 눌러 이메일 인증을 완료해주세요.</p>
    <p><a href="${escapeAttr(verifyUrl)}">이메일 인증하기</a></p>
    <p>이 링크는 ${expiresInHours}시간 동안 유효합니다.</p>
  `;
  return { subject, text, html };
}

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escapeAttr(s: string) {
  return escapeHtml(s).replace(/"/g, "&quot;");
}

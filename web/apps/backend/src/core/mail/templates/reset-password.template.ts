export interface ResetPasswordTemplateParams {
  name: string;
  resetUrl: string;
  expiresInMinutes: number;
}

export function renderResetPasswordTemplate({
  name,
  resetUrl,
  expiresInMinutes,
}: ResetPasswordTemplateParams) {
  const subject = "[ShelfAlign] 비밀번호 재설정";
  const text = [
    `${name}님, 안녕하세요.`,
    "",
    "아래 링크를 눌러 비밀번호를 재설정해주세요. 본인이 요청하지 않았다면 이 메일을 무시해주세요.",
    resetUrl,
    "",
    `이 링크는 ${expiresInMinutes}분 동안 유효합니다.`,
  ].join("\n");
  const html = `
    <p>${escapeHtml(name)}님, 안녕하세요.</p>
    <p>아래 버튼을 눌러 비밀번호를 재설정해주세요.</p>
    <p><a href="${escapeAttr(resetUrl)}">비밀번호 재설정</a></p>
    <p>본인이 요청하지 않았다면 이 메일을 무시해주세요.</p>
    <p>이 링크는 ${expiresInMinutes}분 동안 유효합니다.</p>
  `;
  return { subject, text, html };
}

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escapeAttr(s: string) {
  return escapeHtml(s).replace(/"/g, "&quot;");
}

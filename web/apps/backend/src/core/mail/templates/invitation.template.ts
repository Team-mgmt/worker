export interface InvitationTemplateParams {
  organizationName: string;
  inviterName: string;
  signupUrl: string;
}

export function renderInvitationTemplate({
  organizationName,
  inviterName,
  signupUrl,
}: InvitationTemplateParams) {
  const subject = `[ShelfAlign] ${organizationName} 팀에 초대받았습니다`;
  const text = [
    `${inviterName}님이 ${organizationName} 팀에 회원님을 초대했습니다.`,
    "",
    "아래 링크에서 회원가입을 완료하면 팀에 자동으로 합류됩니다.",
    signupUrl,
  ].join("\n");
  const html = `
    <p><strong>${escapeHtml(inviterName)}</strong>님이 <strong>${escapeHtml(organizationName)}</strong> 팀에 회원님을 초대했습니다.</p>
    <p>아래 버튼을 눌러 회원가입을 완료하면 팀에 자동으로 합류됩니다.</p>
    <p><a href="${escapeAttr(signupUrl)}">회원가입 하러 가기</a></p>
  `;
  return { subject, text, html };
}

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escapeAttr(s: string) {
  return escapeHtml(s).replace(/"/g, "&quot;");
}

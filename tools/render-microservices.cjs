// Deterministic architecture artwork using the locally installed Lucide icon set.
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const React = require(path.join(root, 'frontend/node_modules/react'));
const {renderToStaticMarkup} = require(path.join(root, 'frontend/node_modules/react-dom/server'));
const icons = require(path.join(root, 'frontend/node_modules/lucide-react'));
const {chromium} = require(path.join(root, 'frontend/node_modules/playwright'));
const W=1800,H=1520, p=[];
const colors={identity:'#7754bf',knowledge:'#168169',conversation:'#3265d7'};
const esc=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;');
function t(x,y,s,size=20,color='#182b45',weight=400){p.push(`<text x="${x}" y="${y}" fill="${color}" font-size="${size}" font-weight="${weight}">${esc(s)}</text>`);}
function r(x,y,w,h,fill='#fff',stroke='#dfe6f1',radius=20){p.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" stroke="${stroke}"/>`);}
function icon(name,x,y,color,size=30){p.push(renderToStaticMarkup(React.createElement(icons[name],{size,color,strokeWidth:1.7})).replace('<svg ',`<svg x="${x}" y="${y}" `));}
function card(x,y,w,h,name,title,sub,lines,color='#3265d7'){
 r(x,y,w,h);r(x+22,y+22,50,50,color+'12','none',13);icon(name,x+32,y+32,color);
 t(x+88,y+45,title,25,'#182b45',700);t(x+88,y+72,sub,16,'#61758e');
 lines.forEach((line,i)=>t(x+25,y+115+i*29,line,20,'#61758e'));
}
function arrow(points,color='#3265d7'){
 p.push(`<polyline points="${points.map(a=>a.join(',')).join(' ')}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" marker-end="url(#${color==='#168169'?'green':'blue'})"/>`);
}
p.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs><marker id="blue" markerWidth="9" markerHeight="9" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#3265d7"/></marker><marker id="green" markerWidth="9" markerHeight="9" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#168169"/></marker></defs><g font-family="Malgun Gothic,sans-serif">`);
r(0,0,W,H,'#f7f9fd','none',0);
t(65,70,'SecureDoc Agent',38,'#182b45',700);t(65,115,'마이크로서비스 아키텍처',29,'#182b45',700);
t(65,153,'업무별 독립 이미지 · 전용 DB 계정 · HTTP v1 계약 · 2026.10.17',19,'#61758e');
r(1245,42,490,45,'#eaf0fc','none',22);t(1265,72,'PostgreSQL 1대 / 서비스별 스키마 격리',20,'#3265d7',700);
card(65,220,420,155,'Monitor','사용자 브라우저','React SPA',['채팅 · 문서 · 관리자 화면']);
card(565,220,590,155,'Network','Nginx Gateway :8000','경로별 라우팅 · 요청 ID 전달',['auth → 인증   documents/index → 문서']);
card(1235,220,500,155,'Bot','외부 LLM','Ollama / OpenAI 호환 API',['대화 서비스만 모델 호출'],'#b67827');
arrow([[485,295],[565,295]]);t(495,280,'HTTP',17,'#61758e');
arrow([[850,375],[850,420],[320,420],[320,500]]);arrow([[850,420],[900,420],[900,500]]);arrow([[850,420],[1480,420],[1480,500]]);
t(65,473,'독립 업무 서비스',22,'#182b45',700);
card(65,500,510,290,'ShieldCheck','Identity','microservices/identity · svc_identity',[
 '사용자 · 로그인 · 최신 Workspace 권한', 'JWT 발급 · 비밀번호 변경 시 토큰 무효화', '다른 서비스에 사용자 DB / 서명 키 미제공'],colors.identity);
card(645,500,510,290,'FolderSearch','Knowledge','microservices/knowledge · svc_knowledge',[
 '문서 업로드 · 삭제 · 처리 상태 · 검색 API', '전용 Worker: 파싱 · 임베딩 · 색인', '자기 DB 큐: lease · 재시도 · Outbox 역할'],colors.knowledge);
card(1225,500,510,290,'MessagesSquare','Conversation / RAG','microservices/conversation · svc_conversation',[
 '질문 · LangGraph · 답변 / 근거 검증', '대화 · 메시지 · 인용 스냅샷 저장', '임베딩 / OpenSearch / S3 직접 접근 없음'],colors.conversation);
arrow([[1225,730],[1155,730]],'#168169');t(1157,713,'v1',16,'#168169');
arrow([[1630,500],[1630,375]]);t(1650,455,'모델 호출',17,'#61758e');
t(90,763,'인증 API  /api/v1/auth/me',17,colors.identity);
t(670,763,'내부 검색·출처 검증  /internal/v1/*',17,colors.knowledge);
t(1250,763,'사용자 Bearer + 서비스 키로 검색 호출',17,colors.conversation);
t(65,1148,'Knowledge와 Conversation은 Identity HTTP API로 권한 확인 · 서비스 간 DB JOIN / FK / 공유 트랜잭션 없음',18,'#61758e');
r(65,925,1670,200,'#edf2fc','#d5e0f5',24);icon('Database',90,945,'#61758e',28);
t(135,966,'PostgreSQL · 물리 서버 1대',23,'#182b45',700);t(940,966,'전용 계정은 자기 스키마만 접근 · 다른 스키마 접근 거부',18,'#61758e');
for(const [x,name,line,c] of [[90,'ms_identity','사용자 · Workspace · membership',colors.identity],[670,'ms_knowledge','문서 · 임시 원본 · durable jobs',colors.knowledge],[1250,'ms_conversation','대화 · 메시지 · 인용 스냅샷',colors.conversation]]){
 r(x,990,460,110);t(x+22,1028,name,25,c,700);t(x+22,1067,line,19,'#61758e');
}
arrow([[320,790],[320,925]]);arrow([[900,790],[900,925]],'#168169');arrow([[1480,790],[1480,925]]);
card(65,1200,510,170,'Cloud','S3 / SeaweedFS','원본 파일 · knowledge 전용 자격 증명',['Worker가 저장 / 삭제 · SHA-256 확인'],colors.knowledge);
card(645,1200,510,170,'Search','OpenSearch','문서 벡터 · knowledge 전용 자격 증명',['전체 재색인: 검증 후 alias 원자적 교체'],colors.knowledge);
card(1225,1200,510,170,'Activity','운영 모니터링','Prometheus · Grafana · Alertmanager',['서비스별 오류율 · 큐 정체 / 실패 알람']);
// Storage dependencies leave the knowledge boundary through an outer corridor.
arrow([[1155,600],[1190,600],[1190,880],[1760,880],[1760,1160],[320,1160],[320,1200]],'#168169');
arrow([[900,1160],[900,1200]],'#168169');
t(65,1417,'독립 패치: conversation만 재빌드·재시작 가능 · knowledge 패치 시 같은 서비스 API / Worker 함께 교체',19,'#61758e');
t(65,1454,'공유 인프라 장애는 공통 영향 · 인증 API 장애 시 보호 요청 차단 · 기존 데이터는 별도 이관 후 전환',18,'#61758e');
t(1390,1490,'Icons: Lucide · ISC / MIT',16,'#61758e');
p.push('</g></svg>');const svg=p.join('\n');fs.writeFileSync(path.join(root,'system-architecture.svg'),svg);
fs.copyFileSync(path.join(root,'frontend/node_modules/lucide-react/LICENSE'),path.join(root,'system-architecture-icons-LICENSE.txt'));
(async()=>{const b=await chromium.launch({headless:true});const page=await b.newPage({viewport:{width:W,height:H},deviceScaleFactor:2});await page.setContent(`<html><body style="margin:0">${svg}</body></html>`);await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(root,'system-architecture.png')});await b.close();console.log('Saved microservices PNG/SVG.');})();

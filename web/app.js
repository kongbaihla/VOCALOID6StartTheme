/* V6PAC 前端交互。
 *
 * 后端是 webui.py 里的 Api 类, pywebview 把它挂在 window.pywebview.api 下。
 * 所有方法返回 Promise, 出错时返回 {ok:false,error}。
 *
 * 动画用 GSAP(vendor/gsap.min.js, 本地副本, 离线可用)。
 * reduced 模式下所有动画时长为 0 —— 尊重系统的"减少动态效果"设置。
 */

const $ = (id) => document.getElementById(id);

let api = null;          // window.pywebview.api
let hasImage = false;
let crop = null;         // {cx, cy, zoom} —— 与后端 CropView 一致, cx/cy 是中心点
let imgSize = { w: 0, h: 0 };

/* 动画能力探测: GSAP 缺失或用户要求减少动态时, 一切照常但不动。 */
const GSAP_OK = typeof gsap !== 'undefined';
const REDUCE = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const D = (s) => (REDUCE ? 0 : s);     // 时长包装

if (GSAP_OK) {
  document.body.classList.add('gsap-ready');
  gsap.defaults({ ease: 'power2.out' });
}

/* ------------------------------------------------------------ 启动 */

window.addEventListener('pywebviewready', async () => {
  api = window.pywebview.api;
  intro();
  try {
    const st = await api.bootstrap();
    if (!st.ok) {
      setStatus(st.error || '初始化失败', 'err');
      return;
    }
    paintState(st);
    // paintState 会按可写性写状态文字; 无条件补一句"就绪"会把只读提示
    // 盖掉(第一版就是这样: 界面上有权限警告, 状态栏却写"就绪")。
    if (st.writable) setStatus('就绪');
  } catch (e) {
    setStatus('初始化异常: ' + e, 'err');
  }
});

/* 入场: 侧栏自左滑入, 内容卡依次淡入上浮。
 * 用 timeline 而不是给每个元素配 delay —— 顺序由时间线位置决定, 改起来只看一处。
 * 全部用完 clearProps, 免得 inline 样式留下来干扰 hover / 后续动画。 */
function intro() {
  if (!GSAP_OK || REDUCE) {
    document.body.classList.remove('gsap-ready');
    if (!GSAP_OK) gsap_fallback_show();
    return;
  }

  const tl = gsap.timeline({
    defaults: { ease: 'power3.out' },
    onComplete: () => document.body.classList.remove('gsap-ready'),
  });

  tl.from('.brand', { autoAlpha: 0, x: -10, duration: 0.34, clearProps: 'all' })
    .from('.nav-label', {
      autoAlpha: 0, x: -8, duration: 0.28, stagger: 0.05, clearProps: 'all',
    }, '-=0.16')
    .from('.nav', {
      autoAlpha: 0, x: -10, duration: 0.3, stagger: 0.035, clearProps: 'all',
    }, '-=0.2')
    .from('#card-target', {
      autoAlpha: 0, y: -10, duration: 0.34, clearProps: 'all',
    }, 0.1)
    .from('#page-cover .col', {
      autoAlpha: 0, y: 14, duration: 0.38, stagger: 0.07, clearProps: 'all',
    }, 0.18)
    .from('.out', {
      autoAlpha: 0, y: 10, duration: 0.28, clearProps: 'all',
    }, 0.3);
}

/* 没有 GSAP 时的兜底: 直接显示, 不做任何动画。 */
function gsap_fallback_show() {
  document.querySelectorAll('.brand, .nav, .nav-label, #card-target, #page-cover .col, .out')
    .forEach((el) => { el.style.opacity = '1'; });
}

/* ------------------------------------------------------------ 状态展示 */

function paintState(st) {
  if (!st || !st.ok) return;
  $('dll-path').textContent = st.dllPath;
  $('dll-path').title = st.dllPath;

  const bs = $('badge-status');
  bs.textContent = st.statusLabel;
  // pristine = 原版未替换, 这是"正常"而不是"警告", 用绿色。
  // 只有 applied / other 之类需要提醒的状态才用暖色。
  bs.className = 'badge ' + (st.statusKind === 'pristine' ? 'ok'
    : st.statusKind === 'applied' ? 'ok' : 'warn');

  const bg = $('badge-sig');
  bg.textContent = st.sigText;
  // 后端 signature_status() 返回的是 'Valid' / 'NotSigned' / 'HashMismatch',
  // 首字母大写。这里以前写死了小写 'valid', 比较永远不成立, 于是签名有效时
  // 也显示成橙色警告 —— 需要大小写无关地比较。
  const sigOk = String(st.sigKind || '').toLowerCase() === 'valid';
  bg.className = 'badge ' + (sigOk ? 'ok' : 'warn');

  $('meta-cap').textContent = st.splashCapacity;
  $('meta-size').textContent = st.dllSize;
  $('meta-ver').textContent = st.version;

  // 候选列表: 只有在超过一个时才显示选择器。
  // 本机会同时找到 C:\Program Files 下的 6.13.3.1 和 E:\VOCALOID6 下的
  // 6.13.0.1, 静默"用第一个"很容易改错那个。
  if (Array.isArray(st.candidates)) {
    paintCandidates(st.candidates, st.dllPath);
  }

  if (!st.writable) {
    // 只读状态在启动时就明确告诉用户, 并给出提权入口 —— 否则用户点
    // "应用封面"只会看到一条错误, 不知道该做什么。
    showAdminBar(true);
    setStatus('只读模式：可以预览，应用封面需要管理员权限', 'warn');
  } else {
    showAdminBar(false);
  }
}

function setStatus(msg, kind) {
  const el = $('status-msg');
  el.textContent = msg;
  el.className = 'val' + (kind ? ' ' + kind : '');
}

/* 目标切换。
 *   左侧栏: 只读显示当前目标(版本 · 原版/已修改), 样式与其它导航项一致
 *   右侧卡: 多个候选时平铺成卡片, 点一张就切过去
 * 只有一个候选时右侧不显示, 左侧照样显示当前目标。
 */
let candidates = [];

function paintCandidates(list, current) {
  candidates = list || [];
  const active = candidates.find((c) => c.path === current) || candidates[0];

  // 左侧: 当前目标
  const label = $('target-label');
  const navT = $('nav-target');
  if (label && active) {
    const kind = active.signature === 'Valid' ? '原版' : '已修改';
    label.textContent = `v${active.version} · ${kind}`;
    if (navT) navT.title = active.path;
  } else if (label) {
    label.textContent = '未找到';
  }

  // 右侧: 候选卡片
  const box = $('dll-picker');
  if (!box) return;
  if (candidates.length <= 1) {
    box.hidden = true;
    box.innerHTML = '';
    return;
  }
  box.hidden = false;
  box.innerHTML = candidates.map((c) => {
    const on = c.path === current ? ' on' : '';
    const kind = c.signature === 'Valid'
      ? '<span class="badge ok">原版</span>'
      : '<span class="badge warn">已修改</span>';
    const dir = String(c.path).replace(/[\\/][^\\/]+$/, '');
    return `<div class="dll-card${on}" data-path="${esc(c.path)}" title="${esc(c.path)}">
      <div class="top">
        <span class="ver">v${esc(c.version)}</span>
        ${kind}
        <span class="badge">${esc(c.source)}</span>
      </div>
      <div class="path">${esc(dir)}</div>
    </div>`;
  }).join('');

  box.querySelectorAll('.dll-card').forEach((el) => {
    el.addEventListener('click', () => switchToDll(el.dataset.path));
  });
}

async function switchToDll(path) {
  if (!api) return;
  setStatus('正在切换目标…');
  const st = await api.choose_dll(path);
  if (!st.ok) { setStatus(st.error || '切换失败', 'err'); return; }
  paintState(st);

  // 换了 DLL, 之前的图片预览和备份列表都不再对应, 清掉重来
  hasImage = false;
  crop = null;
  $('crop-img').removeAttribute('src');
  $('effect-img').removeAttribute('src');
  $('crop-box').hidden = true;
  $('crop-empty').hidden = false;
  $('effect-empty').hidden = false;
  $('file-line').textContent = '尚未选择图片';
  $('btn-apply').disabled = true;
  setStatus('目标已切换，请重新选择图片');
}

  // 切换逻辑见 switchToDll(); 这里不再绑 dll-select(已改为卡片式)。

/* ------------------------------------------------------------ 选图 */

$('btn-pick').addEventListener('click', async () => {
  if (!api) return;
  setStatus('正在打开文件选择…');
  const r = await api.pick_image();
  if (r.cancelled) { setStatus('已取消'); return; }
  if (!r.ok) { setStatus(r.error, 'err'); return; }
  applyImage(r);
});

$('btn-default').addEventListener('click', async () => {
  if (!api) return;
  const r = await api.load_default();
  if (!r.ok) { setStatus(r.error, 'err'); return; }
  applyImage(r);
});

function applyImage(r) {
  hasImage = true;
  imgSize = { w: r.width, h: r.height };
  crop = r.crop;

  $('file-line').textContent = `${r.name}  (${r.width} × ${r.height})`;
  $('crop-img').src = r.preview;
  $('crop-empty').hidden = true;
  $('crop-box').hidden = false;
  $('btn-apply').disabled = false;

  $('zoom').value = crop.zoom;
  $('zoom-val').textContent = Number(crop.zoom).toFixed(2) + '×';

  layoutCropBox();
  setStatus('已选择图片');
  refreshEffect();
}

/* ------------------------------------------------------------ 取景框 */

/* 预览图在画布里的实际矩形。
 * 图片用 max-width/height + object-fit:contain 居中显示, 所以它的真实占位
 * 取决于原始宽高比 —— 直接读 clientWidth/clientHeight 即可(浏览器已算好),
 * 再居中换算 left/top。取景框必须以这个矩形为基准, 否则会与图片错位。 */
function imageRect() {
  const img = $('crop-img');
  const wrap = $('crop-wrap');
  const iw = img.clientWidth, ih = img.clientHeight;
  const cw = wrap.clientWidth, ch = wrap.clientHeight;
  return { left: (cw - iw) / 2, top: (ch - ih) / 2, w: iw, h: ih };
}

/* 取景框在显示坐标系里的尺寸。
 *
 * 必须与后端 v6pac_image.crop_box() 用同一套算法, 否则框和实际裁出来的
 * 画面对不上。后端是:
 *     scale = max(TARGET_W/w, TARGET_H/h) * zoom     # base_scale * zoom
 *     bw    = TARGET_W / scale
 *     bh    = TARGET_H / scale
 * 也就是说 zoom=1 时框是"恰好塞进原图的最大 1200:714 矩形"; 我第一版
 * 凭直觉写成了"框高 = 图高/zoom", 对 1200:714 这种本就同比例的图就缩成了
 * 一小块(截图里那个跑到中间的小蓝框)。
 */
const TARGET_W = 1200;
const TARGET_H = 714;

function cropDisplaySize(r) {
  // r.w / r.h 是图片在屏幕上的显示尺寸; 换算比例时用原图尺寸更稳,
  // 因为后端算的是原图坐标。
  const iw = imgSize.w || r.w;
  const ih = imgSize.h || r.h;

  const base = Math.max(TARGET_W / iw, TARGET_H / ih);
  const scale = base * crop.zoom;

  // 框在原图坐标系下的尺寸
  const bw = Math.min(TARGET_W / scale, iw);
  const bh = Math.min(TARGET_H / scale, ih);

  // 原图 → 屏幕的缩放
  const sx = r.w / iw;
  const sy = r.h / ih;
  return { w: bw * sx, h: bh * sy };
}

function layoutCropBox() {
  if (!hasImage || !crop) return;
  const img = $('crop-img');
  if (!img.naturalWidth || !img.clientWidth) return;

  const r = imageRect();
  const box = $('crop-box');
  const { w: dispW, h: dispH } = cropDisplaySize(r);

  // 与后端一致: 中心点落在原图归一化坐标上, 左上角再夹到图内。
  // 不夹的话, 框贴边时会画到图片外面去, 而后端裁出来的图是夹过的 —— 所见非所得。
  const left = clamp(crop.cx * r.w - dispW / 2, 0, Math.max(r.w - dispW, 0));
  const top = clamp(crop.cy * r.h - dispH / 2, 0, Math.max(r.h - dispH, 0));

  box.style.width = Math.max(dispW, 8) + 'px';
  box.style.height = Math.max(dispH, 8) + 'px';
  box.style.left = (r.left + left) + 'px';
  box.style.top = (r.top + top) + 'px';
}

/* 拖动取景框 —— 直接改中心点 cx/cy(归一化), 与后端一致。
 *
 * 性能: 拖动过程中**完全不请求后端**。每次拖都让 Python 重渲 1200x714、
 * 缩成预览、base64 传回(约 114KB), 那个延迟会直接体现在手感上。
 * 这里只移动取景框(纯 CSS), 松手时才推一次后端 —— 这才是"跟手"的做法。
 *
 * 跟手: 按下时记住"鼠标相对框左上角的偏移", 之后每帧都让框保持这个偏移。
 * 早先用的是"鼠标位移 / 可移动范围"的比例映射, 缩放一变框尺寸就变, 同一个
 * 位移对应的移动距离跟着变, 手感就飘了。用偏移量方式, 框永远贴着鼠标原样走。
 */
let dragging = false, dragStart = null;

$('crop-box').addEventListener('mousedown', (e) => {
  if (!hasImage) return;
  const r = imageRect();
  const { w: dispW, h: dispH } = cropDisplaySize(r);
  const left = clamp(crop.cx * r.w - dispW / 2, 0, Math.max(r.w - dispW, 0));
  const top = clamp(crop.cy * r.h - dispH / 2, 0, Math.max(r.h - dispH, 0));

  // 鼠标落在框内的位置(相对框左上角), 拖的时候保持不变
  dragStart = {
    mx: e.clientX,
    my: e.clientY,
    ox: e.clientX - (r.left + left),
    oy: e.clientY - (r.top + top),
  };
  dragging = true;
  $('crop-wrap').classList.add('dragging');
  e.preventDefault();
});

window.addEventListener('mousemove', (e) => {
  if (!dragging) return;
  const r = imageRect();
  const { w: dispW, h: dispH } = cropDisplaySize(r);

  // 目标左上角 = 鼠标位置 - 按下时的偏移
  const wantLeft = e.clientX - dragStart.ox - r.left;
  const wantTop = e.clientY - dragStart.oy - r.top;

  // 夹到图片范围内, 然后从左上角反推中心点
  const maxLeft = Math.max(r.w - dispW, 0);
  const maxTop = Math.max(r.h - dispH, 0);
  const left = clamp(wantLeft, 0, maxLeft);
  const top = clamp(wantTop, 0, maxTop);

  crop.cx = r.w > 0 ? clamp01((left + dispW / 2) / r.w) : 0.5;
  crop.cy = r.h > 0 ? clamp01((top + dispH / 2) / r.h) : 0.5;
  layoutCropBox();          // 只动 DOM, 不碰后端
});

window.addEventListener('mouseup', () => {
  if (!dragging) return;
  dragging = false;
  pushCrop();
});

/* 滚轮缩放 —— 同样只在停止滚轮后再推后端 */
$('crop-wrap').addEventListener('wheel', (e) => {
  if (!hasImage) return;
  e.preventDefault();
  const z = clamp(crop.zoom * (e.deltaY < 0 ? 1.06 : 1 / 1.06), 1, 4);
  crop.zoom = z;
  $('zoom').value = z;
  $('zoom-val').textContent = z.toFixed(2) + '×';
  layoutCropBox();
  schedulePush();
}, { passive: false });

$('zoom').addEventListener('input', () => {
  if (!hasImage) return;
  crop.zoom = Number($('zoom').value);
  $('zoom-val').textContent = crop.zoom.toFixed(2) + '×';
  layoutCropBox();
  schedulePush();
});

/* 停止操作后再算最终效果。250ms 是手感与算力的折中:
 * 太短会连续触发多次渲染, 太长会让人觉得点了没反应。 */
let pushTimer = null;
function schedulePush() {
  clearTimeout(pushTimer);
  pushTimer = setTimeout(pushCrop, 250);
}

async function pushCrop() {
  if (!api || !hasImage) return;
  $('effect-img').classList.add('stale');
  try {
    const r = await api.set_crop(crop.cx, crop.cy, crop.zoom);
    if (r.ok && r.effect) {
      $('effect-img').src = r.effect;
      $('effect-empty').hidden = true;
    }
  } finally {
    $('effect-img').classList.remove('stale');
  }
}

async function refreshEffect() {
  if (!api) return;
  const r = await api.effect();
  if (r.ok && r.effect) {
    $('effect-img').src = r.effect;
    $('effect-empty').hidden = true;
  }
}

$('btn-center').addEventListener('click', async () => {
  if (!api || !hasImage) return;
  const r = await api.center();
  if (!r.ok) return;
  crop = r.crop;
  $('zoom').value = crop.zoom;
  $('zoom-val').textContent = Number(crop.zoom).toFixed(2) + '×';
  layoutCropBox();
  if (r.effect) {
    $('effect-img').src = r.effect;
    $('effect-empty').hidden = true;
  }
  setStatus('已居中');
});

/* ------------------------------------------------------------ 圆角 */

/* 圆角滑块: 只重算右侧预览, 与取景无关。
 * 拖动过程中同样节流 —— 每次都要重新挖角 + 编码, 连续触发会糊。
 * 滑块本身的"关闭 / N.N%"文字是即时的, 只有画面是延迟更新的。 */
let cornerTimer = null;

$('corner').addEventListener('input', () => {
  const v = Number($('corner').value);
  $('corner-val').textContent = v <= 0 ? '关闭' : v.toFixed(1) + '%';
  clearTimeout(cornerTimer);
  cornerTimer = setTimeout(pushCorner, 150);
});

async function pushCorner() {
  if (!api || !hasImage) return;
  $('effect-img').classList.add('stale');
  try {
    const r = await api.set_corner(Number($('corner').value));
    if (r.ok) {
      if (r.effect) {
        $('effect-img').src = r.effect;
        $('effect-empty').hidden = true;
      }
      // 把百分比换算成像素告诉用户, 比单纯一个百分数更好判断
      $('corner-val').textContent =
        r.percent <= 0 ? '关闭' : `${r.percent.toFixed(1)}% · ${r.px}px`;
    }
  } finally {
    $('effect-img').classList.remove('stale');
  }
}

window.addEventListener('resize', layoutCropBox);
$('crop-img').addEventListener('load', layoutCropBox);

/* ------------------------------------------------------------ 应用 */

$('btn-apply').addEventListener('click', async () => {
  if (!api || !hasImage) return;
  const btn = $('btn-apply');
  btn.disabled = true;
  setStatus('正在写入…');
  try {
    const r = await api.apply();
    if (!r.ok) {
      setStatus(r.error, 'err');
      // 权限不足时把提示条亮出来, 不要让用户对着一条错误文字猜怎么办
      if (r.needAdmin) showAdminBar(true);
      return;
    }
    setStatus('已应用', 'ok');
    if (r.state) paintState(r.state);
  } finally {
    btn.disabled = false;
  }
});

/* ------------------------------------------------------------ 提权 */

function showAdminBar(on) {
  const bar = $('admin-bar');
  if (!bar) return;
  bar.hidden = !on;
}

$('btn-elevate').addEventListener('click', async () => {
  if (!api) return;
  const btn = $('btn-elevate');
  btn.disabled = true;
  btn.textContent = '正在请求…';
  try {
    const r = await api.elevate();
    if (r.ok) {
      // 新实例会接管, 当前窗口随后自行关闭
      setStatus('已启动管理员实例，本窗口即将关闭…', 'ok');
    } else if (r.cancelled) {
      setStatus('已取消提权', 'warn');
      btn.disabled = false;
      btn.textContent = '以管理员身份重启';
    } else {
      setStatus(r.error || '提权失败', 'err');
      btn.disabled = false;
      btn.textContent = '以管理员身份重启';
    }
  } catch (e) {
    setStatus('提权异常: ' + e, 'err');
    btn.disabled = false;
    btn.textContent = '以管理员身份重启';
  }
});

/* ------------------------------------------------------------ 页面切换 */

/* 两个页面: cover / backup。
 *
 * 过渡用"旧页淡出 + 新页淡入并轻微位移", 两个方向相反(向左切/向右切),
 * 这样切换方向在视觉上能对上侧栏的顺序感。
 * 动画期间给容器加 .switching 防止连点把状态搞乱。
 */
let currentPage = 'cover';
let switching = false;

function switchPage(name) {
  if (name === currentPage || switching) return;

  document.querySelectorAll('.nav[data-page]').forEach(n =>
    n.classList.toggle('on', n.dataset.page === name));

  const from = $('page-' + currentPage);
  const to = $('page-' + name);
  const forward = (name === 'backup');      // 向后: 内容向左走
  const dir = forward ? -1 : 1;

  if (!GSAP_OK || REDUCE) {
    from.hidden = true;
    to.hidden = false;
    finishSwitch(name);
    return;
  }

  switching = true;

  // 新页先显示出来(但透明), 才能对它做动画
  to.hidden = false;
  gsap.set(to, { autoAlpha: 0, x: dir * 18 });

  const tl = gsap.timeline({
    defaults: { ease: 'power2.out' },
    onComplete: () => {
      switching = false;
      gsap.set([from, to], { clearProps: 'all' });
      from.hidden = true;
      finishSwitch(name);
    },
  });

  tl.to(from, { autoAlpha: 0, x: dir * -14, duration: D(0.16) })
    .to(to, { autoAlpha: 1, x: 0, duration: D(0.26) }, '-=0.04');

  currentPage = name;
}

function finishSwitch(name) {
  currentPage = name;
  if (name === 'backup') loadBackups(true);
}

document.querySelectorAll('.nav[data-page]').forEach(n => {
  n.addEventListener('click', () => switchPage(n.dataset.page));
});

async function loadBackups(animate) {
  if (!api) return;
  const r = await api.backups();
  if (!r.ok) { setStatus(r.error || '读取备份失败', 'err'); return; }
  $('bak-count').textContent =
    `共 ${r.items.length} 份备份 · 当前 DLL 版本 ${r.currentVersion}`;
  renderBackups(r.items, animate);
}

/* 画列表。抽出来是为了删除后能直接重画(不重新请求),
 * 顺便让"原版不可删"这条规则只写在一处。 */
function renderBackups(items, animate) {
  const list = $('bak-list');
  list.innerHTML = '';
  if (!items.length) {
    list.innerHTML = '<div class="file-line">还没有备份。</div>';
    return;
  }
  for (const b of items) {
    const row = document.createElement('div');
    row.className = 'bak-row';
    row.innerHTML = `
      <div class="thumb" data-path="${esc(b.path)}"><span>…</span></div>
      <div class="info">
        <div class="line1">
          <span class="ver">v${esc(b.version)}</span>
          ${b.isOriginal ? '<span class="badge ok">原版</span>'
                         : '<span class="badge warn">已修改</span>'}
          ${b.isCurrent ? '<span class="badge">当前版本</span>' : ''}
          <span class="badge">${esc(b.reason)}</span>
          <span class="file-line">${esc(b.created)}</span>
          <span class="file-line">${esc(b.size)}</span>
        </div>
        <div class="line2" title="${esc(b.name)}">${esc(b.name)}</div>
      </div>
      <button class="btn danger" data-act="del" ${b.isOriginal ? 'disabled title="原版备份不可删除"' : ''}>删除</button>
      <button class="btn" data-act="restore">还原</button>`;
    row.querySelector('[data-act="restore"]')
      .addEventListener('click', () => doRestore(b));
    const delBtn = row.querySelector('[data-act="del"]');
    if (delBtn && !b.isOriginal) {
      delBtn.addEventListener('click', () => doDelete(b));
    }
    list.appendChild(row);
  }

  // 缩略图单独异步取: 首次要从备份 DLL 里导出(约 0.6-0.8 秒), 不能挡住列表先出来。
  // 后端有磁盘缓存, 第二次起是 0 毫秒。
  fillThumbs();

  // 逐行进入。只在切到这一页时播放(animate), 点"刷新"时不重播,
  // 否则每次刷新整个列表都在跳, 反而干扰阅读。
  if (animate && GSAP_OK && !REDUCE) {
    gsap.from('.bak-row', {
      autoAlpha: 0, y: 12, duration: 0.32, stagger: 0.05,
      ease: 'power2.out', clearProps: 'all',
    });
  }
}

/* 删除备份。原版的按钮是 disabled 的, 这里再挡一次 —— 双保险,
 * 因为后端也会拒绝, 但没必要让用户点了才看到错误。 */
async function doDelete(b) {
  const msg = `删除这份备份?\n\n版本 ${b.version}\n${b.created}\n${b.name}\n\n`
    + `文件会被真正删除，无法恢复。`;
  if (!confirm(msg)) return;
  setStatus('正在删除…');
  const r = await api.delete_backup(b.path);
  if (!r.ok) { setStatus(r.message || '删除失败', 'err'); return; }
  setStatus(r.message || '已删除', 'ok');
  if (r.items) {
    const items = Array.isArray(r.items) ? r.items : (r.items.items || []);
    renderBackups(items);
  }
}


/* 逐个填充备份封面缩略图。
 * 串行而不是 Promise.all: 后端每次提取都要起一个 v6res 子进程(约 0.6 秒),
 * 并发起来反而抢磁盘。串行时界面已经能点了, 图一张张出现更自然。 */
async function fillThumbs() {
  const slots = document.querySelectorAll('.bak-list .thumb[data-path]');
  for (const el of slots) {
    if (!api) return;
    try {
      const r = await api.backup_thumb(el.dataset.path);
      if (r.ok && r.thumb) {
        el.innerHTML = `<img src="${r.thumb}" alt="">`;
        if (GSAP_OK && !REDUCE) {
          gsap.from(el.querySelector('img'), { autoAlpha: 0, duration: 0.25 });
        }
      } else {
        el.innerHTML = '<span class="thumb-fail">无</span>';
      }
    } catch (e) {
      el.innerHTML = '<span class="thumb-fail">无</span>';
    }
  }
}


async function doRestore(b) {
  // 把"是不是原版"写进确认框 —— 还原一个改过的备份会把封面一起改掉,
  // 这跟"恢复成出厂状态"是两回事, 用户点之前必须能分清。
  const kind = b.isOriginal ? '原版（签名有效）' : '已修改（签名失效）';
  const warn = b.isOriginal ? '' : '\n\n注意：这不是原版，还原后封面等内容仍是修改过的状态。';
  const msg = `将把 VOCALOID6.dll 还原为:\n\n`
    + `版本 ${b.version}\n${kind}\n${b.reason}  ${b.created}\n\n`
    + `文件: ${b.name}${warn}\n\n`
    + `请确保 VOCALOID6 已完全退出。确定继续吗?`;
  if (!confirm(msg)) return;
  setStatus('正在还原…');
  const r = await api.restore(b.path);
  if (!r.ok) { setStatus(r.error, 'err'); return; }
  setStatus(r.message || '已还原', 'ok');
  if (r.state) paintState(r.state);
  loadBackups();
}

$('btn-bak-refresh').addEventListener('click', loadBackups);

/* ------------------------------------------------------------ 其他操作 */

$('nav-restore-default').addEventListener('click', async () => {
  if (!api) return;
  if (!confirm('将把封面还原为官方默认图。确定继续吗?')) return;
  setStatus('正在还原默认封面…');
  const r = await api.restore_default();
  if (!r.ok) { setStatus(r.error, 'err'); return; }
  setStatus('已还原默认封面', 'ok');
  if (r.state) paintState(r.state);
});

$('nav-upgrade').addEventListener('click', async () => {
  if (!api) return;
  if (!confirm('如果准备升级 VOCALOID6，先用这个把 DLL 还原成原版。\n\n继续吗?')) return;
  const r = await api.upgrade_prepare();
  setStatus(r.message || (r.ok ? '已完成' : r.error), r.ok ? 'ok' : 'err');
  if (r.state) paintState(r.state);
});

$('nav-about').addEventListener('click', () => {
  alert('VOCALOID6 启动封面替换工具\n\n' +
        '替换 VOCALOID6.dll 里的启动封面 / 图标资源。\n' +
        '会修改 DLL 本体，Yamaha 签名将失效（不影响启动）。\n\n' +
        '首次应用前自动备份，永不覆盖已有备份。');
});

/* ------------------------------------------------------------ 工具 */

function clamp01(v) { return Math.min(1, Math.max(0, v)); }
function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

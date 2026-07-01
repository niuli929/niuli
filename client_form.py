#!/usr/bin/env python3
"""
共创坊 · 资源对接表单系统
表单收集 → SQLite 存储 → IMA 知识库备份 → 匹配简报
"""

import sqlite3
import json
import os
import re
from datetime import datetime, timezone, timedelta

from flask import Flask, request, render_template_string, jsonify, redirect

# ─── 配置 ───────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "members.db")
IMA_SYNC_DIR = os.path.join(BASE_DIR, "ima_sync")  # 待同步到 IMA 的摘要

os.makedirs(IMA_SYNC_DIR, exist_ok=True)

# ─── Flask 初始化 ────────────────────────────────────
app = Flask(__name__)

# ─── 数据库初始化 ────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            gender          TEXT    NOT NULL,
            phone           TEXT    NOT NULL,
            hometown        TEXT    NOT NULL DEFAULT '',
            city            TEXT    NOT NULL,
            industry        TEXT    NOT NULL,
            has_company     TEXT    NOT NULL,
            resources       TEXT    NOT NULL,
            biz_intro       TEXT    NOT NULL DEFAULT '',
            privacy_consent INTEGER NOT NULL DEFAULT 0,
            source          TEXT    NOT NULL DEFAULT '微信',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            synced_to_ima   INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ─── 表单 HTML（移动端优先）────────────────────────────
FORM_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>共创坊 · 资源对接登记</title>
<style>
  :root {
    --primary: #1a73e8;
    --primary-light: #e8f0fe;
    --text: #202124;
    --text-secondary: #5f6368;
    --border: #dadce0;
    --bg: #f8f9fa;
    --card-bg: #ffffff;
    --error: #d93025;
    --success: #0d904f;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 16px;
    max-width: 640px;
    margin: 0 auto;
  }
  .header {
    text-align: center;
    padding: 24px 0 16px;
  }
  .header .logo {
    font-size: 36px;
    margin-bottom: 8px;
  }
  .header h1 {
    font-size: 22px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 4px;
  }
  .header p {
    font-size: 14px;
    color: var(--text-secondary);
  }
  .card {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }
  .card-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 2px solid var(--primary-light);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .card-title .icon { font-size: 18px; }
  .form-group {
    margin-bottom: 14px;
  }
  .form-group:last-child { margin-bottom: 0; }
  label {
    display: block;
    font-size: 14px;
    font-weight: 500;
    color: var(--text);
    margin-bottom: 6px;
  }
  label .required {
    color: var(--error);
    margin-left: 2px;
  }
  input[type="text"],
  input[type="tel"],
  select,
  textarea {
    width: 100%;
    padding: 10px 12px;
    font-size: 15px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: #fff;
    color: var(--text);
    outline: none;
    transition: border-color 0.2s;
    -webkit-appearance: none;
    appearance: none;
  }
  input:focus, select:focus, textarea:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 2px var(--primary-light);
  }
  select {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%235f6368' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
    padding-right: 32px;
  }
  textarea {
    min-height: 80px;
    resize: vertical;
  }
  .radio-group, .checkbox-group {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .radio-group label, .checkbox-group label {
    font-size: 14px;
    font-weight: 400;
    padding: 8px 14px;
    border: 1px solid var(--border);
    border-radius: 20px;
    cursor: pointer;
    transition: all 0.2s;
    background: #fff;
    user-select: none;
  }
  .radio-group input, .checkbox-group input {
    display: none;
  }
  .radio-group input:checked + span,
  .checkbox-group input:checked + span {
    color: var(--primary);
  }
  .radio-group label:has(input:checked),
  .checkbox-group label:has(input:checked) {
    background: var(--primary-light);
    border-color: var(--primary);
    color: var(--primary);
  }
  .privacy-box {
    background: #fef7e0;
    border: 1px solid #f9d849;
    border-radius: 8px;
    padding: 12px 14px;
    font-size: 13px;
    color: #5f4b00;
    line-height: 1.6;
    margin-bottom: 12px;
  }
  .privacy-check {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    font-size: 13px;
    color: var(--text-secondary);
  }
  .privacy-check input[type="checkbox"] {
    width: 18px;
    height: 18px;
    margin-top: 2px;
    accent-color: var(--primary);
  }
  .btn-submit {
    width: 100%;
    padding: 14px;
    font-size: 17px;
    font-weight: 600;
    color: #fff;
    background: var(--primary);
    border: none;
    border-radius: 10px;
    cursor: pointer;
    transition: opacity 0.2s;
    margin-top: 8px;
  }
  .btn-submit:active { opacity: 0.85; }
  .btn-submit:disabled { opacity: 0.5; }
  .char-count {
    font-size: 12px;
    color: var(--text-secondary);
    text-align: right;
    margin-top: 4px;
  }
  .char-count.over { color: var(--error); }
  .footer {
    text-align: center;
    padding: 20px 0;
    font-size: 12px;
    color: var(--text-secondary);
  }
  .toast {
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    padding: 12px 24px;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 500;
    color: #fff;
    z-index: 999;
    opacity: 0;
    transition: opacity 0.3s;
    pointer-events: none;
  }
  .toast.show { opacity: 1; }
  .toast.success { background: var(--success); }
  .toast.error { background: var(--error); }
  .hint {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 2px;
  }
</style>
</head>
<body>

<div class="header">
  <div class="logo">🤝</div>
  <h1>共创坊 · 资源对接登记</h1>
  <p>填好你的信息，我们一起撮合更多可能</p>
</div>

<form id="memberForm" onsubmit="handleSubmit(event)">

  <!-- 基本信息 -->
  <div class="card">
    <div class="card-title"><span class="icon">👤</span> 基本信息</div>
    <div class="form-group">
      <label>姓名 <span class="required">*</span></label>
      <input type="text" name="name" id="name" placeholder="你的真实姓名" required maxlength="20">
    </div>
    <div class="form-group">
      <label>性别 <span class="required">*</span></label>
      <div class="radio-group" id="genderGroup">
        <label><input type="radio" name="gender" value="男" required><span>男</span></label>
        <label><input type="radio" name="gender" value="女"><span>女</span></label>
      </div>
    </div>
    <div class="form-group">
      <label>手机号 / 微信号 <span class="required">*</span></label>
      <input type="text" name="phone" id="phone" placeholder="方便我们联系你的方式" required maxlength="30">
      <div class="hint">仅用于资源对接联系，不外泄</div>
    </div>
    <div class="form-group">
      <label>籍贯</label>
      <input type="text" name="hometown" id="hometown" placeholder="如：山东济南" maxlength="20">
    </div>
    <div class="form-group">
      <label>常驻城市 <span class="required">*</span></label>
      <select name="city" id="city" required>
        <option value="">请选择</option>
        <option value="济南">济南</option>
        <option value="青岛">青岛</option>
        <option value="山东其他">山东其他城市</option>
        <option value="北京">北京</option>
        <option value="上海">上海</option>
        <option value="广州">广州</option>
        <option value="深圳">深圳</option>
        <option value="省外其他">省外其他</option>
      </select>
    </div>
  </div>

  <!-- 业务信息 -->
  <div class="card">
    <div class="card-title"><span class="icon">💼</span> 业务信息</div>
    <div class="form-group">
      <label>当前从事的行业 <span class="required">*</span></label>
      <div class="checkbox-group" id="industryGroup">
        <label><input type="checkbox" name="industry" value="餐饮"><span>餐饮</span></label>
        <label><input type="checkbox" name="industry" value="电商"><span>电商</span></label>
        <label><input type="checkbox" name="industry" value="制造业"><span>制造业</span></label>
        <label><input type="checkbox" name="industry" value="服务业"><span>服务业</span></label>
        <label><input type="checkbox" name="industry" value="IT/科技"><span>IT/科技</span></label>
        <label><input type="checkbox" name="industry" value="金融/财税"><span>金融/财税</span></label>
        <label><input type="checkbox" name="industry" value="建筑/房产"><span>建筑/房产</span></label>
        <label><input type="checkbox" name="industry" value="教育/培训"><span>教育/培训</span></label>
        <label><input type="checkbox" name="industry" value="医疗/健康"><span>医疗/健康</span></label>
        <label><input type="checkbox" name="industry" value="贸易/批发"><span>贸易/批发</span></label>
        <label><input type="checkbox" name="industry" value="物流/运输"><span>物流/运输</span></label>
        <label><input type="checkbox" name="industry" value="自媒体"><span>自媒体</span></label>
        <label><input type="checkbox" name="industry" value="其他" id="industryOther"><span>其他</span></label>
      </div>
      <div class="hint">可选多个</div>
    </div>
    <div class="form-group">
      <label>是否已有公司 <span class="required">*</span></label>
      <div class="radio-group" id="companyGroup">
        <label><input type="radio" name="has_company" value="已有公司" required><span>已有公司</span></label>
        <label><input type="radio" name="has_company" value="正在注册"><span>正在注册</span></label>
        <label><input type="radio" name="has_company" value="暂无计划"><span>暂无计划</span></label>
      </div>
    </div>
    <div class="form-group">
      <label>业务介绍</label>
      <textarea name="biz_intro" id="biz_intro" placeholder="简单介绍一下你在做什么，或者想做什么（200字以内）" maxlength="200" oninput="updateCharCount()"></textarea>
      <div class="char-count" id="charCount">0 / 200</div>
    </div>
  </div>

  <!-- 资源需求 -->
  <div class="card">
    <div class="card-title"><span class="icon">🎯</span> 希望对接的资源</div>
    <div class="form-group">
      <label>你最需要什么资源？ <span class="required">*</span></label>
      <div class="checkbox-group" id="resourceGroup">
        <label><input type="checkbox" name="resources" value="供应链"><span>供应链</span></label>
        <label><input type="checkbox" name="resources" value="客户渠道"><span>客户渠道</span></label>
        <label><input type="checkbox" name="resources" value="资金"><span>资金</span></label>
        <label><input type="checkbox" name="resources" value="技术支持"><span>技术支持</span></label>
        <label><input type="checkbox" name="resources" value="人才"><span>人才</span></label>
        <label><input type="checkbox" name="resources" value="工商财税"><span>工商财税</span></label>
        <label><input type="checkbox" name="resources" value="法务咨询"><span>法务咨询</span></label>
        <label><input type="checkbox" name="resources" value="办公场地"><span>办公场地</span></label>
        <label><input type="checkbox" name="resources" value="品牌推广"><span>品牌推广</span></label>
        <label><input type="checkbox" name="resources" value="其他" id="resourceOther"><span>其他</span></label>
      </div>
      <div class="hint">可选多个，选你当前最需要的</div>
    </div>
  </div>

  <!-- 隐私声明 -->
  <div class="card">
    <div class="card-title"><span class="icon">🔒</span> 隐私声明</div>
    <div class="privacy-box">
      📌 <strong>你的信息将如何使用：</strong><br>
      · 仅用于共创坊社群内部资源对接与业务撮合<br>
      · 不会对外公开或出售给第三方<br>
      · 匹配到潜在合作机会时，我们会先征求你的同意再牵线<br>
      · 你可以随时联系我们删除你的信息
    </div>
    <div class="privacy-check">
      <input type="checkbox" name="privacy_consent" id="privacy_consent" value="1" required>
      <label for="privacy_consent">我已阅读并同意以上隐私声明 <span class="required">*</span></label>
    </div>
  </div>

  <button type="submit" class="btn-submit" id="submitBtn">📝 提交信息</button>
  <div style="text-align:center;margin-top:8px;font-size:12px;color:var(--text-secondary)">提交后你的信息将进入共创坊资源库</div>

</form>

<div class="footer">
  © 共创坊 · 让资源流动起来<br>
  技术支持：钮力财税
</div>

<div class="toast" id="toast"></div>

<script>
function updateCharCount() {
  const el = document.getElementById('biz_intro');
  const count = document.getElementById('charCount');
  const len = el.value.length;
  count.textContent = len + ' / 200';
  count.className = 'char-count' + (len > 200 ? ' over' : '');
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type + ' show';
  setTimeout(() => { t.className = 'toast'; }, 3000);
}

function validateCheckboxGroup(name, minCount) {
  const checked = document.querySelectorAll('input[name="'+name+'"]:checked');
  if (checked.length < minCount) return false;
  return true;
}

async function handleSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById('submitBtn');

  // 验证行业至少选一个
  if (!validateCheckboxGroup('industry', 1)) {
    showToast('请至少选择一个行业', 'error');
    return;
  }
  // 验证资源至少选一个
  if (!validateCheckboxGroup('resources', 1)) {
    showToast('请至少选择一项希望对接的资源', 'error');
    return;
  }

  btn.disabled = true;
  btn.textContent = '提交中...';

  const formData = new FormData(e.target);
  // 处理多选字段
  const industry = Array.from(document.querySelectorAll('input[name="industry"]:checked')).map(x => x.value).join(',');
  const resources = Array.from(document.querySelectorAll('input[name="resources"]:checked')).map(x => x.value).join(',');

  // 构建请求体
  const data = {
    name: formData.get('name'),
    gender: formData.get('gender'),
    phone: formData.get('phone'),
    hometown: formData.get('hometown') || '',
    city: formData.get('city'),
    industry: industry,
    has_company: formData.get('has_company'),
    resources: resources,
    biz_intro: formData.get('biz_intro') || '',
    privacy_consent: 1
  };

  try {
    const resp = await fetch('/api/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    const result = await resp.json();
    if (result.code === 0) {
      showToast('✅ 提交成功！你的信息已入库', 'success');
      e.target.reset();
      updateCharCount();
      // 重置多选样式
      document.querySelectorAll('.radio-group label, .checkbox-group label').forEach(l => l.classList.remove('checked'));
    } else {
      showToast(result.msg || '提交失败，请重试', 'error');
    }
  } catch(err) {
    showToast('网络错误，请检查连接后重试', 'error');
  }

  btn.disabled = false;
  btn.textContent = '📝 提交信息';
}
</script>
</body>
</html>"""

SUCCESS_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>提交成功 - 共创坊</title>
<style>
  body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f8f9fa;
    display: flex; justify-content: center; align-items: center;
    min-height: 100vh; margin: 0; padding: 20px;
  }
  .card {
    background: #fff; border-radius: 16px; padding: 40px 30px;
    text-align: center; max-width: 400px; width: 100%;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  }
  .icon { font-size: 56px; margin-bottom: 16px; }
  h1 { font-size: 22px; color: #202124; margin-bottom: 8px; }
  p { font-size: 15px; color: #5f6368; line-height: 1.8; }
  .highlight { color: #1a73e8; font-weight: 600; }
</style>
</head>
<body>
<div class="card">
  <div class="icon">✅</div>
  <h1>提交成功！</h1>
  <p>你的信息已进入<span class="highlight">共创坊资源库</span></p>
  <p>有匹配机会时我们会联系你</p>
  <p style="margin-top:20px;font-size:13px;color:#999;">可以关闭本页面了</p>
</div>
</body>
</html>"""


# ─── 路由 ────────────────────────────────────────────

@app.route("/")
def form_page():
    return render_template_string(FORM_HTML)


@app.route("/api/submit", methods=["POST"])
def submit():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({"code": -1, "msg": f"数据格式错误: {str(e)}"}), 400

    # ── 必填校验 ────────────────────────────────
    required_fields = {
        "name": "姓名",
        "gender": "性别",
        "phone": "手机号/微信号",
        "city": "常驻城市",
        "industry": "行业",
        "has_company": "公司状态",
        "resources": "对接资源",
    }
    for field, label in required_fields.items():
        val = data.get(field, "").strip()
        if not val:
            return jsonify({"code": -1, "msg": f"请填写「{label}」"}), 400

    # 手机号简单校验
    phone = data["phone"].strip()
    if not re.match(r'^[\d\w\-_@.+]{5,30}$', phone):
        return jsonify({"code": -1, "msg": "手机号/微信号格式不太对，检查一下"}), 400

    if not data.get("privacy_consent"):
        return jsonify({"code": -1, "msg": "请同意隐私声明"}), 400

    # ── 写入数据库 ───────────────────────────────
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO members (name, gender, phone, hometown, city, industry, has_company, resources, biz_intro, privacy_consent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            data["name"].strip(),
            data["gender"],
            phone,
            data.get("hometown", "").strip(),
            data["city"],
            data["industry"],
            data["has_company"],
            data["resources"],
            data.get("biz_intro", "").strip(),
        ))
        member_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"code": -1, "msg": f"保存失败: {str(e)}"}), 500
    finally:
        conn.close()

    # ── 生成 IMA 同步摘要 ─────────────────────────
    try:
        summary = generate_summary(member_id, data)
        sync_file = os.path.join(IMA_SYNC_DIR, f"member_{member_id}_{data['name'].strip()}.txt")
        with open(sync_file, "w", encoding="utf-8") as f:
            f.write(summary)
    except Exception:
        pass  # 摘要失败不影响主流程

    return jsonify({
        "code": 0,
        "msg": "提交成功",
        "data": {"id": member_id}
    })


# ─── 管理端：查看所有成员 ─────────────────────────────
@app.route("/admin")
def admin_panel():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, name, gender, phone, hometown, city, industry,
               has_company, resources, biz_intro, created_at, synced_to_ima
        FROM members ORDER BY id DESC
    """).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    conn.close()

    rows_html = ""
    for r in rows:
        synced = "✅" if r["synced_to_ima"] else "⏳"
        rows_html += f"""
        <tr>
          <td>{r['id']}</td>
          <td>{r['name']}</td>
          <td>{r['gender']}</td>
          <td>{r['phone']}</td>
          <td>{r['city']}</td>
          <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{r['industry']}">{r['industry'][:20]}</td>
          <td>{r['has_company']}</td>
          <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{r['resources']}">{r['resources'][:20]}</td>
          <td>{synced}</td>
          <td>{r['created_at']}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>共创坊 · 成员管理</title>
<style>
  body {{ font-family: "PingFang SC","Microsoft YaHei",sans-serif; padding:20px; background:#f8f9fa; }}
  h1 {{ color:#202124; }} .stats {{ color:#5f6368; margin-bottom:16px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
  th,td {{ padding:10px 12px; text-align:left; font-size:13px; border-bottom:1px solid #dadce0; }}
  th {{ background:#1a73e8; color:#fff; font-weight:600; }}
  tr:hover {{ background:#e8f0fe; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; background:#e8f0fe; color:#1a73e8; }}
  a {{ color:#1a73e8; }}
</style></head><body>
<h1>🤝 共创坊 · 成员管理</h1>
<p class="stats">共 <strong>{total}</strong> 位成员 | <a href="/admin/export">📥 导出 CSV</a> | <a href="/admin/matches">🔍 匹配简报</a></p>
<div style="overflow-x:auto">
<table>
  <tr><th>ID</th><th>姓名</th><th>性别</th><th>联系方式</th><th>城市</th><th>行业</th><th>公司</th><th>资源需求</th><th>IMA</th><th>时间</th></tr>
  {rows_html}
</table>
</div>
<p style="margin-top:16px;font-size:12px;color:#999;">本地管理后台，仅服务器可访问</p>
</body></html>"""


@app.route("/admin/export")
def export_csv():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM members ORDER BY id").fetchall()
    conn.close()

    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "姓名", "性别", "联系方式", "籍贯", "城市", "行业", "公司状态", "资源需求", "业务介绍", "提交时间"])
    for r in rows:
        writer.writerow([
            r["id"], r["name"], r["gender"], r["phone"], r["hometown"],
            r["city"], r["industry"], r["has_company"], r["resources"],
            r["biz_intro"], r["created_at"]
        ])

    from flask import Response
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment;filename=members_{datetime.now().strftime('%Y%m%d')}.csv"}
    )


@app.route("/admin/matches")
def match_report():
    """简易匹配简报：找出同一城市、互补行业的人"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM members ORDER BY city, industry").fetchall()
    conn.close()

    # 按城市分组
    by_city = {}
    for r in rows:
        c = r["city"]
        by_city.setdefault(c, []).append(r)

    report = []
    for city, members in by_city.items():
        if len(members) < 2:
            continue
        report.append(f"\n## {city}（{len(members)}人）")
        for m in members:
            report.append(f"  - {m['name']} | {m['industry']} | 需要: {m['resources']} | 公司: {m['has_company']}")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>匹配简报</title>
<style> body {{ font-family:"PingFang SC","Microsoft YaHei",sans-serif; padding:20px; background:#f8f9fa; max-width:800px; margin:0 auto; }}
  h1 {{ color:#202124; }} pre {{ background:#fff; padding:16px; border-radius:8px; white-space:pre-wrap; font-size:14px; line-height:1.8; }}
  a {{ color:#1a73e8; }}
</style></head><body>
<h1>🔍 匹配简报</h1>
<p style="color:#5f6368">按城市分组的成员概览。同城且资源需求互补的可优先撮合。</p>
<pre>{chr(10).join(report) if report else '暂无足够数据生成匹配简报（需要同一城市至少2人）'}</pre>
<p><a href="/admin">← 返回管理</a></p>
</body></html>"""


# ─── 工具函数 ────────────────────────────────────────
def generate_summary(member_id: int, data: dict) -> str:
    """生成成员摘要文本，用于入库 IMA 知识库"""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    return f"""【共创坊成员 · #{member_id}】
提交时间：{now}
━━━━━━━━━━━
姓名：{data['name'].strip()}
性别：{data['gender']}
联系方式：{data['phone'].strip()}
籍贯：{data.get('hometown', '').strip() or '未填'}
常驻城市：{data['city']}
行业：{data['industry']}
是否有公司：{data['has_company']}
希望对接资源：{data['resources']}
业务介绍：{data.get('biz_intro', '').strip() or '未填'}
━━━━━━━━━━━
"""


# ─── 启动 ────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  共创坊 · 资源对接表单系统")
    print("=" * 50)
    print()
    print(f"  数据库: {DB_PATH}")
    print(f"  摘要目录: {IMA_SYNC_DIR}")
    print()
    print("  启动地址: http://127.0.0.1:5000")
    print("  管理后台: http://127.0.0.1:5000/admin")
    print()
    print("  按 Ctrl+C 停止服务器")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)

#!/bin/sh
# P0 spike —— D3 全链路预演原型（只读系统、不改运行态、不需要 root 与挂载）
#
# 断言三件事（真实 /etc/X11/Xsession + 真实 Xsession.d 链）：
#   ① 不带注入块        → rc=0（基线）
#   ② 带【旧】注入块    → rc≠0（2026-09-30 事故回归：必须被判失败）
#   ③ 带【新】注入块    → rc=0（与基线一致，才允许写入）
#
# ── 本机实测踩过的 4 个坑（照抄这份脚本不用再踩）──────────────────────────
# 坑1  `mount -t tmpfs tmpfs /` 在 userns 内**返回 0 但不生效**（findmnt 仍是 ext4），
#      所以"遮罩挂载树"这条路在本机不可用 → 改用「沙箱副本 + 只改一处」。
# 坑2  探针不能放在链尾：`99x11-common_start` 内容是 `exec $STARTUP`，会把 shell
#      整个替换掉，"循环之后"的代码永远不执行 → 探针必须排在 99 之前。
# 坑3  `98vboxadd-xclient` 用 `return`（只结束它自己，无害）；真正会结束 shell 的是
#      `98-lightdm-session-keyboard`（`exit 0`）→ 也要排在它之前。
# 坑4  在自己的复刻循环里用 `printf ... "$?"` 取状态会**掩盖 set -e 的退出信号**
#      （printf 成功即返回 0），会误判成"块无害" → 复刻时不要在 source 与循环体
#      之间插入会改变 $? 的命令。真实 Xsession 没有这层，故本脚本不插入。
#
# 坑5  探针**不能**放链尾：真实 X11 会话里 `70im-config_launch` 会把 $STARTUP 包成
#      `im-launch …`（条件是 `$XDG_SESSION_TYPE != wayland`，X11 必成立），于是
#      `99x11-common_start` 的 `exec` 直接替换 shell —— "循环之后"的代码**真机上同样不可达**。
#      → 探针必须放在 **40x11-common_xsessionrc 之后第一位**：块在这里刚生效，之后
#      任何一步在 set -e 下返回非零都会立刻终止会话（正是事故机制），且这一步必然可达。
set -u

REAL_XSESSION=/etc/X11/Xsession
XSESSION_D=/etc/X11/Xsession.d
SANDBOX=$(mktemp -d /tmp/proxybridge-d3.XXXXXX)
TESTHOME=$SANDBOX/home
NAME_PROBE=41zz-proxybridge-probe   # 目标位置：紧跟 40x11-common_xsessionrc 之后
PROBE_NAME=$NAME_PROBE
PROBE=$SANDBOX/$PROBE_NAME
MARK=$TESTHOME/.probe-mark
mkdir -p "$TESTHOME" "$SANDBOX/run"

NEW_BLOCK='if [ -f "$HOME/.proxy_env" ] && sh -n "$HOME/.proxy_env" 2>/dev/null && ! grep -qE "exit|return|exec" "$HOME/.proxy_env" 2>/dev/null; then set +e; . "$HOME/.proxy_env" 2>/dev/null; fi; true'
OLD_BLOCK='if [ -f "$HOME/.proxy_env" ] && sh -n "$HOME/.proxy_env" 2>/dev/null && ! grep -qE "exit|return|exec" "$HOME/.proxy_env" 2>/dev/null; then set +e; . "$HOME/.proxy_env" 2>/dev/null; set -e; fi; true'

echo "=============================================================="
echo " D3 全链路预演（真实 /etc/X11/Xsession + 真实脚本链 + 链中探针）"
echo "=============================================================="
echo "宿主 /etc/X11/Xsession : $([ -r "$REAL_XSESSION" ] && echo 可读 || echo 不可读)"
echo "真实 Xsession.d 脚本数 : $(ls -1 "$XSESSION_D" | wc -l)"
echo "宿主 ~/.xsessionrc     : $(ls "$HOME/.xsessionrc" 2>/dev/null || echo '不存在')"

# ---------- 造沙箱：① 复制整个真实 Xsession.d ② 放进探针 ③ 只改 SYSSESSIONDIR 一行 ----------
cp "$REAL_XSESSION" "$SANDBOX/Xsession.real" || exit 1
SHA_REAL=$(sha256sum "$SANDBOX/Xsession.real" | cut -d' ' -f1)
mkdir -p "$SANDBOX/Xsession.d" || exit 1
cp -p "$XSESSION_D"/. "$SANDBOX/Xsession.d/" 2>/dev/null || cp -r "$XSESSION_D"/. "$SANDBOX/Xsession.d/" || exit 1
N_REAL=$(ls -1 "$SANDBOX/Xsession.d" | wc -l)
# 探针：留痕（证明被 source）+ 恒返回非零（复刻真机上"某个脚本返回非零"）
printf '#!/bin/sh\n# P0 spike 探针：留痕 + 返回非零（set +e 下被容忍，set -e 下终止会话）\necho "PROBE-REACHED $(date +%%H:%%M:%%S)" >> "$HOME/.probe-mark"\nfalse\n' > "$SANDBOX/Xsession.d/$NAME_PROBE"
chmod 755 "$SANDBOX/Xsession.d/$NAME_PROBE"
# 只改一行：SYSSESSIONDIR 指向沙箱拷贝（其余逐字节保留）
sed "s|^SYSSESSIONDIR=.*|SYSSESSIONDIR=$SANDBOX/Xsession.d|" "$SANDBOX/Xsession.real" > "$SANDBOX/Xsession" || { echo "FAIL sed 失败"; exit 1; }

DIFF_LINES=$(diff "$SANDBOX/Xsession.real" "$SANDBOX/Xsession" | grep -c '^>')
INSERT_HITS=$(grep -cF "SYSSESSIONDIR=$SANDBOX/Xsession.d" "$SANDBOX/Xsession")
echo
echo "--- [0] 沙箱构造校验（必须'只改一处 + 语法可解析'） ---"
echo "副本 sha256(原) : $SHA_REAL"
echo "插入行          : $(grep -F "$PROBE" "$SANDBOX/Xsession")"
echo "差异行数        : $DIFF_LINES（应为 1）"
echo "探针命中        : $INSERT_HITS（应为 1）"
if [ "$DIFF_LINES" -ne 1 ] || [ "$INSERT_HITS" -ne 1 ] || ! dash -n "$SANDBOX/Xsession" 2>/dev/null; then
  echo "FAIL 沙箱副本不满足'只改一处 + 语法可解析'，拒绝继续"; rm -rf "$SANDBOX"; exit 1
fi
# 序位校验：真实 run-parts 对【沙箱拷贝】列出的顺序里，探针必须紧跟 40 号
RP_LIST=$(run-parts --list "$SANDBOX/Xsession.d" 2>/dev/null | xargs -n1 basename)
N_RP=$(printf '%s\n' "$RP_LIST" | grep -c .)
BEFORE_PROBE=$(printf '%s\n' "$RP_LIST" | grep -B1 -x "$PROBE_NAME" | head -1)
AFTER_PROBE=$(printf '%s\n' "$RP_LIST" | grep -A1 -x "$PROBE_NAME" | tail -1)
echo "沙箱 Xsession.d : $N_REAL 个真实脚本 + 1 个探针 = $N_RP 个（run-parts 实列）"
echo "探针序位        : [${BEFORE_PROBE:-?}] → [$PROBE_NAME] → [${AFTER_PROBE:-?}]"
if [ "$BEFORE_PROBE" != "40x11-common_xsessionrc" ] || [ "$N_RP" -ne $((N_REAL + 1)) ]; then
  echo "FAIL 探针没有紧跟 40 号（或 run-parts 没收录），D3 语义不成立"; rm -rf "$SANDBOX"; exit 1
fi
echo "探针内容        : $(tr '\n' '|' < "$SANDBOX/Xsession.d/$NAME_PROBE")"

run_case() {
  label=$1
  block=$2
  rm -rf "$TESTHOME" 2>/dev/null || true
  mkdir -p "$TESTHOME" || return 90
  printf '%s\n' "$block" > "$TESTHOME/.xsessionrc"
  # 夹具：块的第一句是 [ -f "$HOME/.proxy_env" ]，没有它块整段不执行 → 假通过（踩过）
  if [ -n "$block" ]; then
    printf 'export http_proxy="http://127.0.0.1:7897"\nexport no_proxy="localhost,127.0.0.1"\n' > "$TESTHOME/.proxy_env"
  else
    rm -f "$TESTHOME/.proxy_env"
  fi
  # shellcheck disable=SC2086
  (
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
    HOME=$TESTHOME; USER=ypipaq; LOGNAME=ypipaq; SHELL=/bin/sh
    STARTUP=/bin/true
    XDG_SESSION_TYPE=x11
    XDG_RUNTIME_DIR=$SANDBOX/run
    TMPDIR=/tmp
    USERXSESSIONRC=$TESTHOME/.xsessionrc
    export PATH HOME USER LOGNAME SHELL STARTUP XDG_SESSION_TYPE XDG_RUNTIME_DIR TMPDIR USERXSESSIONRC
    dash "$SANDBOX/Xsession"          # 用 dash：与真实 shebang #!/bin/sh 在本机一致
  )
  rc=$?
  if [ -f "$MARK" ]; then reached="探针已执行✅"; else reached="探针未到❌"; fi
  errf="$TESTHOME/.xsession-errors"
  printf '  %-22s rc=%-3s %s  errors=%-6s\n' \
    "$label" "$rc" "$reached" "$([ -f "$errf" ] && wc -c < "$errf" | tr -d ' ' || echo none)"
  return $rc
}

echo
echo "--- [1] 三组用例（探针留痕可观测） ---"
run_case "① 不带块（基线）"  ''
BASE_RC=$?
run_case "② 旧块（set -e）"  "$OLD_BLOCK"
OLD_RC=$?
run_case "③ 新块（v1）"      "$NEW_BLOCK"
NEW_RC=$?

echo
echo "--- [2] 断言 ---"
p=0; f=0
if [ "$BASE_RC" -eq 0 ]; then echo "  PASS ① 基线 rc=0"; p=$((p+1)); else echo "  FAIL ① 基线 rc=$BASE_RC（期望 0）"; f=$((f+1)); fi
if [ "$OLD_RC"  -ne 0 ]; then echo "  PASS ② 旧块 rc=$OLD_RC ≠ 0（事故被判失败）"; p=$((p+1)); else echo "  FAIL ② 旧块 rc=0（事故漏判！）"; f=$((f+1)); fi
if [ "$NEW_RC"  -eq 0 ]; then echo "  PASS ③ 新块 rc=0（与基线一致）"; p=$((p+1)); else echo "  FAIL ③ 新块 rc=$NEW_RC（期望 0）"; f=$((f+1)); fi
echo "  ---- $p PASS / $f FAIL ----"

echo
echo "--- [3] 宿主污染检查（只读断言） ---"
echo "宿主探针残留          : $(ls "$XSESSION_D"/41zz-proxybridge-probe 2>/dev/null || echo none)"
echo "宿主 Xsession sha256  : $(sha256sum "$REAL_XSESSION" | cut -d' ' -f1)"
echo "                  原值: $SHA_REAL"
echo "宿主 ~/.xsessionrc    : $(ls "$HOME/.xsessionrc" 2>/dev/null || echo '不存在（未被碰）')"

rm -rf "$SANDBOX" 2>/dev/null || true
echo
if [ "$f" -eq 0 ]; then echo "D3 预演: OK（三组可重复）"; exit 0; else echo "D3 预演: FAIL"; exit 1; fi

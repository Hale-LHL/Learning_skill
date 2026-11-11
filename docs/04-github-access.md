# 在受限网络下访问本仓库

> 这份文档解决一个非常具体的问题：**DNS 能解析 github.com，但连不上，报 TLS 错误或证书错误**。
>
> 如果你访问 GitHub 一切正常，这篇可以跳过。

## 现象长什么样

典型症状（按出现频率排序）：

| 命令 | 报错 |
|---|---|
| `git clone/push https://github.com/...` | `schannel: server closed abruptly (missing close_notify)` |
| `curl https://github.com` | exit code 35（SSL connect error），几毫秒就失败 |
| `ssh -T git@github.com` | `Connection refused` 或握手卡住超时 |
| `ssh -p 443 -T git@ssh.github.com` | banner 显示一串十六进制（如 `a07fe5ff`）——**这不是 GitHub**，GitHub 真实 banner 是 `babeld-*` |

## 根因：不是全封，是「按 IP 封」

这是最容易误判的地方。实测（2026-11，中国大陆某校园网）：

```
DNS 解析 github.com        → 20.205.243.166     ← 这个 IP 的 443 被 RST
curl --resolve 到 140.82.112.3                  → HTTP 000（被 RST）
curl --resolve 到 140.82.121.3                  → HTTP 200 ✅
curl --resolve 到 140.82.113.3                  → HTTP 000
curl --resolve 到 140.82.116.3                  → HTTP 200 ✅
```

同一时刻，同一个域名，**换个官方 IP 就能通**。而且可用性会变化：今天 112.3 通、明天封了，121.3 又活了。

问题在于 **git 没法指定「用哪个 IP 去解析域名」**。`GIT_SSL_NO_VERIFY`、换协议、换端口都解决不了——它们改变不了连接的目标 IP。

## 解法：本地 CONNECT 隧道

`tools/gh_tunnel.py` 在本机起一个最小 HTTP CONNECT 代理，把 `github.com:443` 的字节流转发到一个当前可达的官方 IP。

```bash
# 1. 先看看当前哪些 IP 可用
python tools/gh_tunnel.py --scan

# 2. 起隧道（前台开着，或丢后台）
python tools/gh_tunnel.py

# 3. 让 git 走隧道
git -c http.proxy=http://127.0.0.1:8899 push origin main
```

**为什么这样做是安全的**：隧道只搬运 TCP 字节，**不做 TLS 中间人**。TLS 握手仍然发生在 git 和 GitHub 之间，SNI 是 `github.com`，证书由 GitHub 签发、由 git 校验。隧道不持有任何证书，也无法解密流量。

**为什么不能不测 TCP 就转发**：被阻断的 IP 照样能完成 TCP 三次握手，然后在 TLS `ClientHello` 阶段被重置。所以 `gh_tunnel.py` 的探活做的是**真实 TLS 握手 + 一个 HEAD 请求**，拿到 HTTP 响应才算通过。只 `socket.connect()` 判断可用性会误判——这是本项目第一版踩过的坑。

## 让配置常驻

每次都敲 `-c http.proxy=...` 很烦。可以在仓库里设一次：

```bash
git config --local http.proxy http://127.0.0.1:8899
```

之后 `git push` / `git fetch` 自动走隧道。代价是：**隧道没起时 git 会报连接失败**，而不是报网络超时。心里有数就行。

## 认证这件事

隧道解决了「能不能连上」，不解决「GitHub 认不认你」。两个独立问题。

本机实测：

- **SSH 不可行**：22 端口被拒；`ssh.github.com:443` 的 banner 不是 GitHub 的（见上文），说明 443 通道被中间设备干扰
- **GCM 不可行**：`git-credential-manager.exe` 在非 TTY 环境（agent、CI、脚本）下直接报 `/dev/tty: No such device or address`，不会弹 GUI
- **可用方案**：Personal Access Token（classic，勾 `repo`）

```bash
git -c credential.helper= push \
  "https://<token>@github.com/<user>/<repo>.git" main:main
```

`-c credential.helper=` 是必须的——否则 git 会去调 GCM，在非交互环境里卡死。

**令牌不要写进 `.git/config`**，用 URL 临时带一次。推完检查：

```bash
grep -r "ghp_" .git/ && echo "有残留，清理" || echo "干净"
```

## 已知的坑

1. **可用 IP 会变**。`CANDIDATES` 里的列表是实测快照，不是永久真理。连不上时先跑 `--scan`。
2. **探测结果是缓存的**（120 秒）。刚被封的 IP 会继续被用 2 分钟，失败后会自动降级重试并强制重扫。
3. **`refs/remotes/origin/main` 可能写不进去**（某些机器的文件系统中间件会拦截 `.git` 下的写入）。表现是 `git status` 显示 `main...origin/main [gone]`。绕过：
   ```bash
   git config branch.main.remote origin
   git config branch.main.merge refs/heads/main
   ```
4. **这只是绕行，不是修复**。换网络环境（手机热点、公司网）后可能直接就好了，不必一直挂着隧道。

## 不推荐的替代方案

- `GIT_SSL_NO_VERIFY=true`：关掉证书校验，解决不了 IP 被 RST 的问题，还引入中间人风险
- 各种 `ghproxy` / `gh-proxy` 镜像：**只读**，能 clone 不能 push，且稳定性不由你控制
- 改 hosts 绑 IP：需要管理员权限，且 IP 一变就得改，比隧道麻烦

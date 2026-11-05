// AwakeWindow — 极简菜单栏组件
// 左键单击 = 登记「接下来 30 分钟不合盖」；右键 = 菜单（续期 / 改时长 / 结束 / 退出）
// 作用：写一个可信的"活着窗口"信号给 Hermes；窗口内阻止 idle 睡眠（合盖仍会睡，符合语义）
//
// 2026-10-22：主人要求「姐姐也能被这只鲸鱼唤醒」——触发从「只看 default profile」
// 扩成「两个 profile 各触发各的夜巡」，配额、冷却、日志全部按 profile 分开算。咻

import Cocoa
import Foundation
import Darwin

let kDir = NSHomeDirectory() + "/.hermes/awake"
let kFile = kDir + "/window.json"
let kLog = kDir + "/history.log"
let kDefaultMinutes = 30

let kOpenNote = Notification.Name("local.ryanian.awakewindow.open")
let kCloseNote = Notification.Name("local.ryanian.awakewindow.close")
let kMenuNote = Notification.Name("local.ryanian.awakewindow.menu")

// ---- QQ 通道（NapCat + OneBot）一键切换 ----
// 上线 = 入口切 NapCat + launchd 拉起 + 插件启用 + 网关重启
// 下线 = launchd 停 + 插件停用 + 入口切回原版 + 网关重启
// ⚠️ 改 QQ 的 package.json 需要「系统设置 → 隐私与安全性 → App 管理」里放行 AwakeWindow，
//    这是 macOS 的 TCC，sudo 也绕不过去（TCC 看调用进程，不看 uid）。
let kQQPackage = "/Applications/QQ.app/Contents/Resources/app/package.json"
let kQQPackageBak = kQQPackage + ".bak"
let kQQOriginalMain = "./application.asar/app_launcher/index.js"
let kQQNapCatMain = NSHomeDirectory() + "/Library/Containers/com.tencent.qq/Data/Documents/loadNapCat.js"
let kQQLaunchdLabel = "com.napcat.qq"
let kQQPlist = NSHomeDirectory() + "/Library/LaunchAgents/com.napcat.qq.plist"
let kQQWebUI = "http://127.0.0.1:6099/webui"
let kQQPort: UInt16 = 3001

// 文档后台（本地数据看板）：菜单栏入口
let kHubPort: UInt16 = 8788
let kHubURL = "http://127.0.0.1:8788/"
let kHubLabel = "com.hermes.docs-hub"
let kHubHTML = NSHomeDirectory() + "/Desktop/文档后台/index.html"
let kHubScript = NSHomeDirectory() + "/.hermes/scripts/docs_hub.py"
let kHubPython = "/opt/homebrew/bin/python3"
var kHubStatus = "检测中…"

// 姐妹群聊（本地 web 群聊）：菜单栏入口
let kSistersPort: UInt16 = 8770
let kSistersURL = "http://127.0.0.1:8770/"
let kSistersLabel = "com.hermes.sisters-chat"
let kSistersDir = NSHomeDirectory() + "/Desktop/姐妹群聊"
var kSistersStatus = "检测中…"      // 子菜单里那行详细状态
var kSistersShort = "检测中…"       // 父项标题后缀，不点开也看得到
/// 改入口这一步只有它有 TCC 授权，菜单只能请它代劳
let kNapCatInstallerApp = NSHomeDirectory() + "/Downloads/napcat/NapCatInstaller.app"

func qqReadMain() -> String? {
    guard let data = FileManager.default.contents(atPath: kQQPackage),
          let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
    return obj["main"] as? String
}

func qqUsesNapCat() -> Bool { (qqReadMain() ?? "").contains("loadNapCat") }

/// 端口能不能连上：连得上就算通道活着
func qqPortReady() -> Bool {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    if fd < 0 { return false }
    defer { close(fd) }
    var tv = timeval(tv_sec: 1, tv_usec: 0)
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
    var addr = sockaddr_in()
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = kQQPort.bigEndian
    addr.sin_addr.s_addr = inet_addr("127.0.0.1")
    let rc = withUnsafePointer(to: &addr) { p in
        p.withMemoryRebound(to: sockaddr.self, capacity: 1) { sp in
            connect(fd, sp, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    return rc == 0
}

/// 文档后台的本地服务活着没（连得上 127.0.0.1:8788 就算活）
func hubPortReady() -> Bool {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    if fd < 0 { return false }
    defer { close(fd) }
    var tv = timeval(tv_sec: 0, tv_usec: 300_000)
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
    var addr = sockaddr_in()
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = kHubPort.bigEndian
    addr.sin_addr.s_addr = inet_addr("127.0.0.1")
    let rc = withUnsafePointer(to: &addr) { p in
        p.withMemoryRebound(to: sockaddr.self, capacity: 1) { sp in
            connect(fd, sp, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    return rc == 0
}

/// 姐妹群聊的本地服务活着没（连得上 127.0.0.1:8770 就算活）
func sistersPortReady() -> Bool {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    if fd < 0 { return false }
    defer { close(fd) }
    var tv = timeval(tv_sec: 1, tv_usec: 0)
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
    var addr = sockaddr_in()
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = kSistersPort.bigEndian
    addr.sin_addr.s_addr = inet_addr("127.0.0.1")
    let rc = withUnsafePointer(to: &addr) { p in
        p.withMemoryRebound(to: sockaddr.self, capacity: 1) { sp in
            connect(fd, sp, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    return rc == 0
}

/// 后台查一次服务与数据时间，结果写进 kHubStatus（菜单里只读缓存，不阻塞弹菜单）
func refreshHubStatus() {
    DispatchQueue.global(qos: .utility).async {
        var s = "服务未运行 · 点「打开看板」会拉起"
        if hubPortReady() {
            s = "在线"
            let (_, out) = qqShell("curl -s -m 1.5 http://127.0.0.1:8788/api/status")
            if let r = out.range(of: "\"generated_at\": \"") {
                let rest = out[r.upperBound...]
                if let e = rest.firstIndex(of: "\"") {
                    let ts = String(rest[..<e])            // 2026-10-31 12:13:21
                    if ts.count >= 16 { s = "在线 · 数据 " + String(ts.suffix(8)) }
                }
            }
        }
        DispatchQueue.main.async { kHubStatus = s }
    }
}

/// 后台问一次 /api/ping，结果写进 kSistersStatus（菜单只读缓存）
func refreshSistersStatus() {
    DispatchQueue.global(qos: .utility).async {
        var short = "未运行"
        var s = "服务未运行 · 点「打开群聊」会拉起"
        if sistersPortReady() {
            let (_, out) = qqShell("curl -s -m 1.5 http://127.0.0.1:8770/api/ping")
            var name = ""
            var n = ""
            if let r = out.range(of: "\"session\": \"") {
                let rest = out[r.upperBound...]
                if let e = rest.firstIndex(of: "\"") { name = String(rest[..<e]) }
            }
            if let r = out.range(of: "\"count\": ") {
                let rest = out[r.upperBound...]
                if let e = rest.firstIndex(where: { !$0.isNumber }) { n = String(rest[..<e]) }
            }
            short = n.isEmpty ? "在线" : "在线 · \(n) 条"
            s = name.isEmpty ? short : "在线 · \(name) · \(n) 条"
        }
        DispatchQueue.main.async { kSistersShort = short; kSistersStatus = s }
    }
}

/// 只改 package.json 里 main 那一行，其余格式原样保留
func qqSetMain(_ main: String) -> Bool {
    guard var text = try? String(contentsOfFile: kQQPackage, encoding: .utf8) else { return false }
    if !FileManager.default.fileExists(atPath: kQQPackageBak) {
        try? FileManager.default.copyItem(atPath: kQQPackage, toPath: kQQPackageBak)
    }
    guard let r = text.range(of: "\"main\"\\s*:\\s*\"[^\"]*\"", options: .regularExpression) else { return false }
    text.replaceSubrange(r, with: "\"main\" : \"\(main)\"")
    do { try text.write(toFile: kQQPackage, atomically: true, encoding: .utf8); return true } catch { return false }
}

@discardableResult
func qqShell(_ cmd: String) -> (Int32, String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/bin/bash")
    p.arguments = ["-lc", cmd]
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    do { try p.run() } catch { return (-1, error.localizedDescription) }
    let out = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(data: out, encoding: .utf8) ?? "")
}

/// 上线/下线全过程。改 QQ 入口这一步只有 NapCat 安装器有 TCC 授权，
/// 所以这里自动打开安装器、轮询等用户点按钮，检测到入口变了就自动接着做完剩下的事。
func qqSetChannel(online: Bool, completion: @escaping (Bool, String) -> Void) {
    let finish: (Bool, String) -> Void = { ok, msg in
        DispatchQueue.main.async { completion(ok, msg) }
    }
    DispatchQueue.global(qos: .userInitiated).async {
        var notes: [String] = []

        // 1) 先让入口对齐（需要主线程弹窗引导 + 用户点一下安装器按钮）
        if qqUsesNapCat() != online {
            let target = online ? "NapCat" : "原版 QQ"
            DispatchQueue.main.async {
                NSApp.activate(ignoringOtherApps: true)
                let a = NSAlert()
                a.messageText = "需要先切到\(target)入口"
                a.informativeText = "已为你打开 NapCat 安装器。点一下「切换程序入口『\(target)』」，我这边会自动接着做完剩下的步骤（最多等 3 分钟）。\n\n为什么不能全自动：改 QQ 包内文件是 macOS 的 App 管理保护，只有安装器拿了授权。"
                a.addButton(withTitle: "去点一下")
                a.runModal()
                NSWorkspace.shared.open(URL(fileURLWithPath: kNapCatInstallerApp))
            }
            var aligned = false
            for _ in 0..<180 {
                Thread.sleep(forTimeInterval: 1)
                if qqUsesNapCat() == online { aligned = true; break }
            }
            guard aligned else {
                finish(false, "等了 3 分钟，入口还没切到\(target)。可能安装器没点按钮，或它在等 App 管理授权。")
                return
            }
            notes.append("入口→\(target)")
        }

        // 2) 服务与插件
        if online {
            _ = qqShell("launchctl enable gui/501/\(kQQLaunchdLabel); launchctl bootstrap gui/501 \"\(kQQPlist)\"")
            notes.append("launchd 已拉起")
            _ = qqShell("\(kHermesBin) plugins enable onebot-platform")
            notes.append("插件已启用")
            var up = false
            for _ in 0..<40 {
                if qqPortReady() { up = true; break }
                Thread.sleep(forTimeInterval: 1)
            }
            notes.append(up ? "3001 就绪" : "3001 未就绪（看 ~/Library/Logs/napcat.log）")
        } else {
            _ = qqShell("launchctl bootout gui/501/\(kQQLaunchdLabel) 2>/dev/null; launchctl disable gui/501/\(kQQLaunchdLabel)")
            notes.append("launchd 已停")
            _ = qqShell("\(kHermesBin) plugins disable onebot-platform")
            notes.append("插件已停")
        }

        // 3) 网关重启让平台真正上下线
        _ = qqShell("\(kHermesBin) gateway restart")
        notes.append("网关已重启")
        finish(true, notes.joined(separator: " · "))
    }
}

// ---- 触发夜巡：点一下就喊人 ----
let kHermesBin = NSHomeDirectory() + "/.hermes/hermes-agent/.hermes/bin/hermes"
let kTriggerCooldown: TimeInterval = 600  // 每个 profile 各自 10 分钟内不重复喊
let kMinMinutesToTrigger = 10             // 窗口不足 10 分钟不值得起一趟会话
let kDailyVideoCap = 4                    // 两个号的每日视频上限都是 4（mini_env.sh 里也是 4）

/// 一个「夜巡宿主」：谁的队列、谁的配额账本、怎么调用她的 cron
struct NightWatchTarget {
    let label: String        // 日志里的名字：小鲸鱼 / 小大姐
    let jobsJson: String     // 该 profile 的 cron/jobs.json
    let nightLog: String     // 该 profile 的 night_log.json（配户口径分开）
    let jobName: String      // cron 里那条任务的**精确**名字
    let profileArgs: [String] // 调 hermes 时要带的 profile 参数
    let cooldownKey: String  // UserDefaults 里各自的冷却键
}

let kNightWatchTargets: [NightWatchTarget] = [
    NightWatchTarget(
        label: "小鲸鱼",
        jobsJson: NSHomeDirectory() + "/.hermes/cron/jobs.json",
        nightLog: NSHomeDirectory() + "/.hermes/bili/night_log.json",
        jobName: "B站夜巡",
        profileArgs: [],
        cooldownKey: "lastTrigger.default"
    ),
    NightWatchTarget(
        label: "小大姐",
        jobsJson: NSHomeDirectory() + "/.hermes/profiles/glm/cron/jobs.json",
        nightLog: NSHomeDirectory() + "/.hermes/profiles/glm/bili/night_log.json",
        jobName: "小大姐夜巡",
        profileArgs: ["-p", "glm"],
        cooldownKey: "lastTrigger.glm"
    ),
]

/// 从状态文件现算剩余分钟（顶层版本，供触发逻辑使用）
func remainingMinutesGlobal() -> Int {
    guard let data = FileManager.default.contents(atPath: kFile),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let active = obj["active"] as? Bool, active,
          let epoch = obj["until_epoch"] as? Double else { return 0 }
    let s = epoch - Date().timeIntervalSince1970
    if s <= 0 { return 0 }
    return max(1, Int((s / 60).rounded(.up)))
}

/// 在该 profile 的 jobs.json 里找**名字精确匹配**的那条夜巡。
/// 优先取「最早的未来候选点」（点一下就是想马上干活，别去挑隔天那条）；
/// 没有未来时间字段时退回第一个 enabled 的。
func findNightWatchJobId(target: NightWatchTarget) -> String? {
    guard let data = FileManager.default.contents(atPath: target.jobsJson),
          let root = try? JSONSerialization.jsonObject(with: data) else { return nil }
    var jobs: [[String: Any]] = []
    if let a = root as? [[String: Any]] {
        jobs = a
    } else if let d = root as? [String: Any], let a = d["jobs"] as? [[String: Any]] {
        jobs = a
    }
    let nowIso = isoString(Date())
    var best: (id: String, nr: String)?
    for j in jobs {
        guard let name = j["name"] as? String else { continue }
        guard name == target.jobName else { continue }   // 精确匹配：别把「夜巡守卫」当成夜巡
        if let enabled = j["enabled"] as? Bool, !enabled { continue }
        guard let id = j["id"] as? String else { continue }
        let nr = (j["next_run_at"] as? String) ?? (j["next_run"] as? String) ?? ""
        if !nr.isEmpty, nr > nowIso {
            if best == nil || nr < best!.nr { best = (id, nr) }
        }
    }
    if let b = best { return b.id }
    for j in jobs {
        guard let name = j["name"] as? String, name == target.jobName else { continue }
        if let enabled = j["enabled"] as? Bool, !enabled { continue }
        if let id = j["id"] as? String { return id }
    }
    return nil
}

func triggerNightWatch(target: NightWatchTarget) {
    // 窗口太短就别喊人：10 分钟以下起一趟会话不划算
    let rem = remainingMinutesGlobal()
    guard rem >= kMinMinutesToTrigger else {
        appendLog("NO_TRIGGER\t\(target.label)\twindow too short (\(rem)min < \(kMinMinutesToTrigger))")
        return
    }
    // 该 profile 今日配额满了也别喊（省一趟会话）
    let count = todayVideoCount(nightLog: target.nightLog)
    guard let n = count, n < kDailyVideoCap else {
        appendLog("NO_TRIGGER\t\(target.label)\tquota full (\(count ?? -1)/\(kDailyVideoCap))")
        return
    }
    let now = Date().timeIntervalSince1970
    let last = UserDefaults.standard.double(forKey: target.cooldownKey)
    if last > 0, now - last < kTriggerCooldown {
        appendLog("NO_TRIGGER\t\(target.label)\tcooldown \(Int(now - last))s")
        return
    }
    guard let jobId = findNightWatchJobId(target: target) else {
        appendLog("NO_TRIGGER\t\(target.label)\tno active \(target.jobName) job found")
        return
    }
    UserDefaults.standard.set(now, forKey: target.cooldownKey)

    let p = Process()
    p.executableURL = URL(fileURLWithPath: kHermesBin)
    p.arguments = target.profileArgs + ["cron", "run", jobId, "--accept-hooks"]
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    p.terminationHandler = { _ in
        let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(),
                         encoding: .utf8) ?? ""
        appendLog("TRIGGER\t\(target.label)\t\(jobId)\t\(out.trimmingCharacters(in: .whitespacesAndNewlines))")
    }
    do {
        try p.run()
        appendLog("TRIGGER_SENT\t\(target.label)\t\(jobId)")
    } catch {
        appendLog("TRIGGER_FAIL\t\(target.label)\t\(error.localizedDescription)")
    }
}

/// 一次点击 = 两边都问一遍，各自过自己的配额与冷却
func triggerAllNightWatch() {
    for t in kNightWatchTargets { triggerNightWatch(target: t) }
}

// ---- 今天的看片配额（读各自的 night_log.json，口径与 bili_quota.py 一致）----
// 这些标题/动作是「回话、收信」记录，不是看片
let kMetaTitlePrefixes = ["本次运行元信息", "自发评论", "本次运行", "心跳收信", "心跳"]

func todayVideoCount(nightLog: String) -> Int? {
    guard let data = FileManager.default.contents(atPath: nightLog),
          let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]
    else { return nil }
    let f = DateFormatter()
    f.dateFormat = "yyyy-MM-dd"
    f.timeZone = TimeZone.current
    let today = f.string(from: Date())
    var seen = Set<String>()
    for r in arr {
        guard let d = r["date"] as? String, d == today else { continue }
        // 口径同 bili_quota.py 的 is_watch_record()：只有真打开过的视频才吃额度。
        // 在别人评论区回话时记录里也挂着 bvid，但那不是看片（曾造成 5/4 假满额）。
        let bvid = ((r["bvid"] as? String) ?? "").trimmingCharacters(in: .whitespaces)
        let title = ((r["title"] as? String) ?? "").trimmingCharacters(in: .whitespaces)
        let action = (r["action"] as? String) ?? ""
        guard bvid.hasPrefix("BV") else { continue }
        let seenMark = action.contains("toview-add") || action.contains("seen=")
        let isReplyLog = kMetaTitlePrefixes.contains(where: { title.hasPrefix($0) })
            || action.hasPrefix("ack") || action.hasPrefix("comment")
        if isReplyLog && !seenMark { continue }
        seen.insert(bvid)
    }
    return seen.count
}

// ---- 命令行触发口（供快捷指令 / 脚本 / Hermes 使用） ----
func handleCLIAndMaybeExit() {
    let args = CommandLine.arguments
    let dc = DistributedNotificationCenter.default()
    if args.contains("--quota") {
        for t in kNightWatchTargets {
            if let n = todayVideoCount(nightLog: t.nightLog) {
                let left = max(0, kDailyVideoCap - n)
                FileHandle.standardOutput.write(
                    "\(t.label): today=\(n) cap=\(kDailyVideoCap) left=\(left)\n".data(using: .utf8)!)
            } else {
                FileHandle.standardOutput.write("\(t.label): unknown\n".data(using: .utf8)!)
            }
        }
        exit(0)
    }
    // ---- 文档后台：命令行入口（快捷指令 / 终端 / Hermes 都能用）----
    if args.contains("--hub-status") {
        let up = hubPortReady()
        let (_, out) = up ? qqShell("curl -s -m 1.5 http://127.0.0.1:8788/api/status") : (0, "")
        let line = up ? out : "service DOWN\n"
        FileHandle.standardOutput.write(line.data(using: .utf8)!)
        exit(0)
    }
    if args.contains("--hub-rebuild") {
        let (code, out) = qqShell("\(kHubPython) \(kHubScript) 2>&1 | tail -1")
        FileHandle.standardOutput.write(out.data(using: .utf8)!)
        exit(code == 0 ? 0 : 1)
    }
    if args.contains("--hub") {
        if !hubPortReady() {
            _ = qqShell("launchctl kickstart -k gui/$(id -u) \(kHubLabel) 2>/dev/null")
            for _ in 0..<16 {
                Thread.sleep(forTimeInterval: 0.25)
                if hubPortReady() { break }
            }
        }
        let target = hubPortReady() ? kHubURL : kHubHTML
        _ = qqShell("open '\(target)'")
        FileHandle.standardOutput.write("open \(target)\n".data(using: .utf8)!)
        exit(0)
    }
    // 姐妹群聊自检：只读，不碰服务
    if args.contains("--sisters-status") {
        let up = sistersPortReady()
        var line = "port=\(kSistersPort) \(up ? "up" : "down")"
        if up {
            let (_, out) = qqShell("curl -s -m 1.5 http://127.0.0.1:8770/api/ping")
            line += " · " + out.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        FileHandle.standardOutput.write((line + "\n").data(using: .utf8)!)
        exit(0)
    }
    // 打开群聊（服务没起就先拉起）
    if args.contains("--sisters") {
        if !sistersPortReady() {
            _ = qqShell("launchctl kickstart -k gui/$(id -u) \(kSistersLabel) 2>/dev/null")
            for _ in 0..<24 {
                Thread.sleep(forTimeInterval: 0.25)
                if sistersPortReady() { break }
            }
        }
        if sistersPortReady() {
            _ = qqShell("open '\(kSistersURL)'")
            FileHandle.standardOutput.write("open \(kSistersURL)\n".data(using: .utf8)!)
            exit(0)
        }
        FileHandle.standardOutput.write("service down: \(kSistersLabel) not answering on \(kSistersPort)\n".data(using: .utf8)!)
        exit(1)
    }
    if args.contains("--menu") {
        dc.postNotificationName(kMenuNote, object: nil, userInfo: nil, deliverImmediately: true)
        FileHandle.standardOutput.write("posted menu\n".data(using: .utf8)!)
        exit(0)
    }
    if args.contains("--extend"), let i = args.firstIndex(of: "--extend"),
       i + 1 < args.count, let m = Int(args[i + 1]), m > 0 {
        dc.postNotificationName(Notification.Name("local.ryanian.awakewindow.extend"),
                                object: nil, userInfo: ["minutes": m], deliverImmediately: true)
        FileHandle.standardOutput.write("posted extend \(m)m\n".data(using: .utf8)!)
        exit(0)
    }
    if args.contains("--find-job") {
        for t in kNightWatchTargets {
            let id = findNightWatchJobId(target: t) ?? "none"
            FileHandle.standardOutput.write("\(t.label): job=\(id)\n".data(using: .utf8)!)
        }
        exit(0)
    }
    // QQ 通道自检：不碰任何状态，只报当前入口/端口/launchd 情况
    if args.contains("--qq-status") {
        let main = qqReadMain() ?? "(读不到)"
        let mode = qqUsesNapCat() ? "napcat" : "original"
        let port = qqPortReady() ? "up" : "down"
        let (lc, lout) = qqShell("launchctl list \(kQQLaunchdLabel) 2>/dev/null | tail -1")
        let raw = lout.trimmingCharacters(in: .whitespacesAndNewlines)
        let launchd = (lc == 0 && !raw.isEmpty) ? raw : "not-loaded"
        let line = "mode=\(mode) port=\(port) main=\(main) launchd=\(launchd)\n"
        FileHandle.standardOutput.write(line.data(using: .utf8)!)
        exit(0)
    }
    if args.contains("--qq-online") { qqSetChannel(online: true) { _, m in print(m); exit(0) }; RunLoop.main.run() }
    if args.contains("--qq-offline") { qqSetChannel(online: false) { _, m in print(m); exit(0) }; RunLoop.main.run() }
    if args.contains("--trigger") {
        triggerAllNightWatch()
        Thread.sleep(forTimeInterval: 4)
        exit(0)
    }
    // 只喊一边（调试/验证用）
    if args.contains("--trigger-default"), let t = kNightWatchTargets.first {
        triggerNightWatch(target: t); Thread.sleep(forTimeInterval: 2); exit(0)
    }
    if args.contains("--trigger-minimax"), kNightWatchTargets.count > 1 {
        triggerNightWatch(target: kNightWatchTargets[1]); Thread.sleep(forTimeInterval: 2); exit(0)
    }
    if let i = args.firstIndex(of: "--open"), i + 1 < args.count, let m = Int(args[i + 1]), m > 0 {
        dc.postNotificationName(kOpenNote, object: nil,
                                userInfo: ["minutes": m], deliverImmediately: true)
        FileHandle.standardOutput.write("posted open \(m)m\n".data(using: .utf8)!)
        exit(0)
    }
    if args.contains("--close") {
        dc.postNotificationName(kCloseNote, object: nil, userInfo: nil, deliverImmediately: true)
        FileHandle.standardOutput.write("posted close\n".data(using: .utf8)!)
        exit(0)
    }
}

func isoString(_ d: Date) -> String {
    let f = ISO8601DateFormatter()
    f.timeZone = TimeZone.current
    f.formatOptions = [.withInternetDateTime]
    return f.string(from: d)
}

func appendLog(_ line: String) {
    let stamp = isoString(Date())
    let text = "\(stamp)\t\(line)\n"
    if let fh = FileHandle(forWritingAtPath: kLog) {
        fh.seekToEndOfFile()
        fh.write(text.data(using: .utf8)!)
        fh.closeFile()
    } else {
        try? text.write(toFile: kLog, atomically: true, encoding: .utf8)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var untilDate: Date?
    var activity: NSObjectProtocol?
    var timer: Timer?

    func applicationDidFinishLaunching(_ note: Notification) {
        try? FileManager.default.createDirectory(atPath: kDir, withIntermediateDirectories: true)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let b = statusItem.button {
            b.target = self
            b.action = #selector(handleClick(_:))
            b.sendAction(on: [.leftMouseUp, .rightMouseUp])
            b.imagePosition = .noImage
        }

        // 外部触发口：监听 distributed notification
        let dc = DistributedNotificationCenter.default()
        dc.addObserver(forName: kOpenNote, object: nil, queue: .main) { [weak self] n in
            let m = (n.userInfo?["minutes"] as? Int) ?? kDefaultMinutes
            self?.openWindow(minutes: m)
        }
        dc.addObserver(forName: kCloseNote, object: nil, queue: .main) { [weak self] _ in
            self?.closeWindow(reason: "remote_close")
        }
        dc.addObserver(forName: kMenuNote, object: nil, queue: .main) { [weak self] _ in
            self?.showMenu()
        }
        dc.addObserver(forName: Notification.Name("local.ryanian.awakewindow.extend"),
                       object: nil, queue: .main) { [weak self] n in
            let m = (n.userInfo?["minutes"] as? Int) ?? 10
            self?.extendWindow(byMinutes: m)
        }

        // 冷启动时接管尚未过期的窗口
        if let d = readActiveWindow() {
            untilDate = d
            holdSleep()
            appendLog("RESUME\tuntil \(isoString(d))")
        }
        refresh()
        refreshHubStatus()
        refreshSistersStatus()

        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.tick()
        }
        RunLoop.current.add(timer!, forMode: .common)
    }

    // MARK: - 核心状态

    func readActiveWindow() -> Date? {
        guard let data = FileManager.default.contents(atPath: kFile),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let active = obj["active"] as? Bool, active,
              let epoch = obj["until_epoch"] as? Double else { return nil }
        let d = Date(timeIntervalSince1970: epoch)
        return d > Date() ? d : nil
    }

    func commitWindow(until: Date, labelMinutes: Int, verb: String) {
        let now = Date()
        untilDate = until
        let payload: [String: Any] = [
            "active": true,
            "until": isoString(until),
            "until_epoch": until.timeIntervalSince1970,
            "created": isoString(now),
            "created_epoch": now.timeIntervalSince1970,
            "duration_minutes": labelMinutes,
            "pid": ProcessInfo.processInfo.processIdentifier,
            "source": "AwakeWindow.app",
            "note": "用户手动登记：接下来电脑不合盖"
        ]
        if let data = try? JSONSerialization.data(withJSONObject: payload,
                                                  options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: URL(fileURLWithPath: kFile), options: .atomic)
        }
        appendLog("\(verb)\t\(labelMinutes)min\tuntil \(isoString(until))")
        holdSleep()
        refresh()
        NSSound(named: "Tink")?.play()
    }

    /// 从此刻起设定一个 N 分钟窗口
    func openWindow(minutes: Int) {
        commitWindow(until: Date().addingTimeInterval(Double(minutes) * 60),
                     labelMinutes: minutes, verb: "OPEN")
    }

    /// 在现有剩余时间上继续累加（右键 +10）
    func extendWindow(byMinutes m: Int) {
        let now = Date()
        let base = (untilDate.map { $0 > now ? $0 : now }) ?? now
        let target = base.addingTimeInterval(Double(m) * 60)
        let total = max(1, Int((target.timeIntervalSince(now) / 60).rounded(.up)))
        commitWindow(until: target, labelMinutes: total, verb: "EXTEND+\(m)")
    }

    func closeWindow(reason: String) {
        let wasOpen = untilDate != nil
        untilDate = nil
        releaseSleep()
        let payload: [String: Any] = [
            "active": false,
            "closed_at": isoString(Date()),
            "reason": reason
        ]
        if let data = try? JSONSerialization.data(withJSONObject: payload,
                                                  options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: URL(fileURLWithPath: kFile), options: .atomic)
        }
        if wasOpen { appendLog("CLOSE\t\(reason)") }
        refresh()
    }

    // MARK: - 防睡眠（只挡 idle，不挡合盖）

    func holdSleep() {
        if activity != nil { return }
        activity = ProcessInfo.processInfo.beginActivity(
            options: [.idleSystemSleepDisabled, .userInitiatedAllowingIdleSystemSleep],
            reason: "AwakeWindow: user registered an awake window"
        )
    }

    func releaseSleep() {
        if let a = activity {
            ProcessInfo.processInfo.endActivity(a)
            activity = nil
        }
    }

    // MARK: - 刷新

    func remainingMinutes() -> Int? {
        guard let u = untilDate else { return nil }
        let s = u.timeIntervalSinceNow
        if s <= 0 { return 0 }
        return max(1, Int(ceil(s / 60.0)))
    }

    func refresh() {
        guard let b = statusItem.button else { return }
        func setTitle(_ text: String, dim: Bool) {
            let color: NSColor = dim ? .tertiaryLabelColor : .labelColor
            b.attributedTitle = NSAttributedString(
                string: text,
                attributes: [
                    .foregroundColor: color,
                    .font: NSFont.systemFont(ofSize: 12, weight: dim ? .regular : .semibold)
                ]
            )
        }
        if let m = remainingMinutes(), m > 0 {
            b.appearsDisabled = false
            setTitle("🐋 \(m)m", dim: false)
            b.toolTip = "醒着窗口开启中 · 剩余 \(m) 分钟"
        } else {
            setTitle("🐋", dim: true)
            b.toolTip = "未登记 · 点一下说「我接下来 30 分钟不合盖」"
        }
    }

    func tick() {
        if let u = untilDate, u.timeIntervalSinceNow <= 0 {
            closeWindow(reason: "expired")
        } else {
            refresh()
        }
    }

    // MARK: - 交互

    @objc func handleClick(_ sender: Any?) {
        let ev = NSApp.currentEvent
        let isRight = ev?.type == .rightMouseUp
            || ev?.modifierFlags.contains(.control) == true
        if isRight {
            // 右键：在当前剩余时间上直接 +10 分钟
            extendWindow(byMinutes: 10)
            triggerAllNightWatch()
        } else {
            // 左键：弹档位菜单（调时长 / 关闭）
            showMenu()
        }
    }

    func showMenu() {
        let menu = NSMenu()
        if let m = remainingMinutes(), m > 0 {
            let head = NSMenuItem(title: "醒着中 · 还剩 \(m) 分钟", action: nil, keyEquivalent: "")
            head.isEnabled = false
            menu.addItem(head)
        } else {
            let head = NSMenuItem(title: "没开窗口 · 选个时长", action: nil, keyEquivalent: "")
            head.isEnabled = false
            menu.addItem(head)
        }
        menu.addItem(.separator())

        // 档位：点一下就从此刻起开这么久
        let tiers: [(Int, String)] = [
            (10, "10 分钟 · 发评论够用"),
            (20, "20 分钟 · 能看一个短的"),
            (30, "30 分钟 · 一个视频 + 评论"),
            (60, "60 分钟 · 宽裕"),
        ]
        for (mins, label) in tiers {
            let it = NSMenuItem(title: label, action: #selector(menuPick(_:)), keyEquivalent: "")
            it.target = self
            it.tag = mins
            menu.addItem(it)
        }
        menu.addItem(.separator())

        // 今日配额：让主人知道点了这一下有没有活可干（两个号各一行）
        for t in kNightWatchTargets {
            if let n = todayVideoCount(nightLog: t.nightLog) {
                let left = max(0, kDailyVideoCap - n)
                let qText = left > 0
                    ? "\(t.label) 今日 \(n)/\(kDailyVideoCap) 个 · 还能补 \(left) 个"
                    : "\(t.label) 今日 \(n)/\(kDailyVideoCap) 个 · 满额，只回消息"
                let qi = NSMenuItem(title: qText, action: nil, keyEquivalent: "")
                qi.isEnabled = false
                menu.addItem(qi)
            }
        }
        menu.addItem(.separator())

        // QQ 通道（NapCat / OneBot）：一键上下线
        let qqRoot = NSMenuItem(title: "QQ 通道", action: nil, keyEquivalent: "")
        let qqSub = NSMenu()
        let napcat = qqUsesNapCat()
        let stateItem = NSMenuItem(
            title: napcat ? "NapCat · " + (qqPortReady() ? "在线" : "未就绪") : "原版 QQ · 离线",
            action: nil, keyEquivalent: "")
        stateItem.isEnabled = false
        qqSub.addItem(stateItem)
        qqSub.addItem(.separator())
        let onItem = NSMenuItem(title: "上线（切 NapCat 入口）", action: #selector(menuQQOnline), keyEquivalent: "")
        onItem.target = self
        qqSub.addItem(onItem)
        let offItem = NSMenuItem(title: "下线（切回原版 QQ）", action: #selector(menuQQOffline), keyEquivalent: "")
        offItem.target = self
        qqSub.addItem(offItem)
        qqSub.addItem(.separator())
        let webItem = NSMenuItem(title: "打开 NapCat WebUI", action: #selector(menuQQWebUI), keyEquivalent: "")
        webItem.target = self
        qqSub.addItem(webItem)
        qqRoot.submenu = qqSub
        menu.addItem(qqRoot)
        menu.addItem(.separator())

        // 文档后台：本地数据看板（六人消息/资金/定时/B站/文档 一屏八页）
        refreshHubStatus()
        let hubRoot = NSMenuItem(title: "文档后台", action: nil, keyEquivalent: "")
        let hubSub = NSMenu()
        let hubState = NSMenuItem(title: kHubStatus, action: nil, keyEquivalent: "")
        hubState.isEnabled = false
        hubSub.addItem(hubState)
        hubSub.addItem(.separator())
        let hubOpen = NSMenuItem(title: "打开看板", action: #selector(menuOpenDashboard), keyEquivalent: "")
        hubOpen.target = self
        hubSub.addItem(hubOpen)
        let hubBuild = NSMenuItem(title: "立即重生成", action: #selector(menuRebuildDashboard), keyEquivalent: "")
        hubBuild.target = self
        hubSub.addItem(hubBuild)
        let hubShow = NSMenuItem(title: "在 Finder 里显示", action: #selector(menuRevealDashboard), keyEquivalent: "")
        hubShow.target = self
        hubSub.addItem(hubShow)
        hubRoot.submenu = hubSub
        menu.addItem(hubRoot)
        menu.addItem(.separator())

        // 姐妹群聊：本地 web 群聊（六人同时开麦那种）
        let sisRoot = NSMenuItem(title: "姐妹群聊 · \(kSistersShort)", action: nil, keyEquivalent: "")
        let sisSub = NSMenu()
        let sisState = NSMenuItem(title: kSistersStatus, action: nil, keyEquivalent: "")
        sisState.isEnabled = false
        sisSub.addItem(sisState)
        sisSub.addItem(.separator())
        let sisOpen = NSMenuItem(title: "打开群聊", action: #selector(menuOpenSisters), keyEquivalent: "")
        sisOpen.target = self
        sisSub.addItem(sisOpen)
        let sisRestart = NSMenuItem(title: "重启服务", action: #selector(menuRestartSisters), keyEquivalent: "")
        sisRestart.target = self
        sisSub.addItem(sisRestart)
        let sisShow = NSMenuItem(title: "在 Finder 里显示", action: #selector(menuRevealSisters), keyEquivalent: "")
        sisShow.target = self
        sisSub.addItem(sisShow)
        sisRoot.submenu = sisSub
        menu.addItem(sisRoot)
        menu.addItem(.separator())
        menu.addItem(.separator())

        if remainingMinutes() != nil {
            let c = NSMenuItem(title: "关闭窗口", action: #selector(menuClose), keyEquivalent: "")
            c.target = self
            menu.addItem(c)
            menu.addItem(.separator())
        }

        let q = NSMenuItem(title: "退出", action: #selector(menuQuit), keyEquivalent: "")
        q.target = self
        menu.addItem(q)

        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil
    }

    @objc func menuPick(_ sender: NSMenuItem) {
        let mins = sender.tag
        openWindow(minutes: mins)
        if mins >= 10 { triggerAllNightWatch() }
    }
    @objc func menuClose() { closeWindow(reason: "user_cancel") }
    @objc func menuQuit() { NSApp.terminate(nil) }

    // MARK: - QQ 通道

    @objc func menuQQOnline() { runQQChannel(online: true) }
    @objc func menuQQOffline() { runQQChannel(online: false) }
    @objc func menuQQWebUI() {
        if let u = URL(string: kQQWebUI) { NSWorkspace.shared.open(u) }
    }

    // MARK: - 文档后台

    /// 打开看板：服务没在跑就先 kickstart 拉起，拉不起来退回直接开文件
    @objc func menuOpenDashboard() {
        if hubPortReady() {
            if let u = URL(string: kHubURL) { NSWorkspace.shared.open(u) }
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            _ = qqShell("launchctl kickstart -k gui/$(id -u) \(kHubLabel) 2>/dev/null")
            var ok = false
            for _ in 0..<16 {
                Thread.sleep(forTimeInterval: 0.25)
                if hubPortReady() { ok = true; break }
            }
            DispatchQueue.main.async {
                if ok {
                    appendLog("HUB_OPEN\tvia-service")
                    if let u = URL(string: kHubURL) { NSWorkspace.shared.open(u) }
                } else {
                    appendLog("HUB_OPEN\tvia-file\t(service kickstart failed)")
                    NSWorkspace.shared.open(URL(fileURLWithPath: kHubHTML))
                }
                refreshHubStatus()
            }
        }
    }

    /// 立即重生成（不用等 cron 的 2 小时）
    @objc func menuRebuildDashboard() {
        DispatchQueue.global(qos: .userInitiated).async {
            let (code, out) = qqShell("\(kHubPython) \(kHubScript) 2>&1 | tail -1")
            let line = out.trimmingCharacters(in: .whitespacesAndNewlines)
            appendLog("HUB_REBUILD\t\(code)\t\(line)")
            DispatchQueue.main.async { refreshHubStatus() }
            if code != 0 {
                DispatchQueue.main.async {
                    let a = NSAlert()
                    a.messageText = "看板重生成失败"
                    a.informativeText = line.isEmpty ? "exit \(code)" : line
                    a.addButton(withTitle: "好")
                    a.runModal()
                }
            } else {
                let safe = line.replacingOccurrences(of: "\"", with: "")
                _ = qqShell("osascript -e 'display notification \"\(safe)\" with title \"文档后台\"'")
            }
        }
    }

    @objc func menuRevealDashboard() {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: kHubHTML)])
    }

    // MARK: - 姐妹群聊

    /// 打开群聊：服务没在跑就先 kickstart 拉起来，拉不起来就报清楚怎么手动起
    @objc func menuOpenSisters() {
        if sistersPortReady() {
            if let u = URL(string: kSistersURL) { NSWorkspace.shared.open(u) }
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            _ = qqShell("launchctl kickstart -k gui/$(id -u) \(kSistersLabel) 2>/dev/null")
            var ok = false
            for _ in 0..<24 {
                Thread.sleep(forTimeInterval: 0.25)
                if sistersPortReady() { ok = true; break }
            }
            DispatchQueue.main.async {
                if ok {
                    appendLog("SISTERS_OPEN\tvia-service")
                    if let u = URL(string: kSistersURL) { NSWorkspace.shared.open(u) }
                } else {
                    appendLog("SISTERS_OPEN\tfail\t(kickstart failed)")
                    let a = NSAlert()
                    a.messageText = "群聊服务起不来"
                    a.informativeText = "试过 launchctl kickstart \(kSistersLabel)，8770 还是没人应答。\n可以手动跑：~/Desktop/姐妹群聊/启动.command"
                    a.addButton(withTitle: "好")
                    a.runModal()
                }
                refreshSistersStatus()
            }
        }
    }

    /// 重启服务（改完 server.py 之后不用自己去终端敲）
    @objc func menuRestartSisters() {
        DispatchQueue.global(qos: .userInitiated).async {
            _ = qqShell("launchctl kickstart -k gui/$(id -u) \(kSistersLabel) 2>/dev/null")
            var ok = false
            for _ in 0..<28 {
                Thread.sleep(forTimeInterval: 0.25)
                if sistersPortReady() { ok = true; break }
            }
            appendLog("SISTERS_RESTART\t\(ok ? "ok" : "fail")")
            DispatchQueue.main.async {
                refreshSistersStatus()
                if !ok {
                    let a = NSAlert()
                    a.messageText = "重启失败"
                    a.informativeText = "launchctl kickstart \(kSistersLabel) 之后端口还是不通。"
                    a.addButton(withTitle: "好")
                    a.runModal()
                }
            }
        }
    }

    @objc func menuRevealSisters() {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: kSistersDir)])
    }

    func runQQChannel(online: Bool) {
        qqSetChannel(online: online) { ok, msg in
            appendLog("QQ_CHANNEL\t\(online ? "online" : "offline")\t\(ok ? "ok" : "fail")\t\(msg)")
            NSApp.activate(ignoringOtherApps: true)
            let a = NSAlert()
            a.messageText = ok ? (online ? "QQ 通道已上线" : "QQ 通道已下线") : "切换失败"
            a.informativeText = msg
            a.addButton(withTitle: "好")
            a.runModal()
        }
    }
}

handleCLIAndMaybeExit()

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()

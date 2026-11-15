// The Mac app's settings window over the running game: the launcher's own view (Launcher.swift LauncherView, with the iOS launcher's model and rows), linked into the Mac host
// (dm/host/Makefile) and opened by front_mac.m with ⌘, (the app menu's Settings…) or a short press of a controller's Home button. It lies over the game's view inside the game's
// window, so the window keeps the keyboard and the game its focus: the game keeps running, and a change to the picture shows on its next frame. While it is open the game gets no
// input (front_mac.m holds it); a controller moves through the rows (dm_settings_panel_nav).
// A choice is saved as the launcher saves it (launcher.<VAR> in the app's preferences, only when it differs from the tested default), so the next start has it. A setting the
// running game takes at once (front_setting_live: front_mac.m for HDR, the Metal HUD and the display mode, settings_live.c for the tone map, the grade, the frame rate, upscaling,
// the render scale and rumble) is applied as it changes; the others say "Applies at next start", and Restart Game starts the game again through the launcher
// (front_settings_restart, launcher.c) when there is one. The list is the app's Resources/dm/launcher.json, else the file DM_SETTINGS_LIST names (a host run outside an app);
// DM_SETTINGS_DOMAIN keeps the choices in that preferences domain instead of the app's (a test run)
import AppKit
import Combine
import SwiftUI

@_silgen_name("front_setting_live") private func front_setting_live(_ env: UnsafePointer<CChar>, _ value: UnsafePointer<CChar>?) -> Int32
@_silgen_name("front_settings_closed") private func front_settings_closed()
@_silgen_name("front_settings_restart") private func front_settings_restart() -> Int32
@_silgen_name("front_settings_log") private func front_settings_log(_ s: UnsafePointer<CChar>)   // the host log (not dm_log: Swift cannot call a variadic C function)

private func log(_ s: String) { s.withCString { front_settings_log($0) } }

final class GameSettings {
    static var shared: GameSettings?
    let model: LauncherModel
    private let start: [String: String]   // the values the game started with: a setting that needs the next start differs from them
    private var last: [String: String]
    private var sub: AnyCancellable?
    private var view: NSView?
    var isOpen: Bool { view != nil }

    static func load() -> GameSettings? {
        if let g = shared { return g }
        var url = Bundle.main.resourceURL?.appendingPathComponent("dm/launcher.json")
        if let p = getenv("DM_SETTINGS_LIST") { url = URL(fileURLWithPath: String(cString: p)) }
        guard let url, let data = try? Data(contentsOf: url) else { log("no settings list (an app's Resources/dm/launcher.json, or DM_SETTINGS_LIST)"); return nil }
        guard let file = try? JSONDecoder().decode(SettingsFile.self, from: data), !file.settings.isEmpty else { log("[RED] \(url.path) cannot be read"); return nil }
        let defaults = getenv("DM_SETTINGS_DOMAIN").flatMap { UserDefaults(suiteName: String(cString: $0)) } ?? .standard
        shared = GameSettings(file.settings, defaults)
        return shared
    }

    private init(_ settings: [Setting], _ defaults: UserDefaults) {
        model = LauncherModel(settings, defaults: defaults, running: true)
        model.live = { s in s.env.withCString { front_setting_live($0, nil) } != 0 }
        start = model.values; last = model.values
        sub = model.$values.sink { [weak self] new in self?.changed(new) }   // willSet: the new values, before the view reads them
        log("\(settings.count) settings, \(settings.filter { model.live?($0) ?? false }.count) of them live")
    }

    private func changed(_ new: [String: String]) {
        for s in model.settings where !model.fixed.contains(s.env) {
            guard let v = new[s.env], v != last[s.env] else { continue }
            model.save(s, v)
            if model.live?(s) ?? false {
                let ok = s.env.withCString { e in v.withCString { front_setting_live(e, $0) } } != 0
                log("\(s.env)=\(v) \(ok ? "applied" : "not taken") and saved")
            } else { log("\(s.env)=\(v) saved for the next start") }
        }
        last = new
        let pending = model.settings.contains { !(model.live?($0) ?? false) && !model.fixed.contains($0.env) && new[$0.env] != start[$0.env] }
        if pending != model.pendingRestart { DispatchQueue.main.async { self.model.pendingRestart = pending } }
    }

    func open(in parent: NSView) {
        guard view == nil else { return }
        let actions = InGameActions(resume: { [weak self] in self?.close() }, quit: { NSApp.terminate(nil) },
                                    restart: getenv("DM_LAUNCHER_RESTART") != nil ? { _ = front_settings_restart() } : nil)
        let root = LauncherView(m: model, done: { _ in }, fit: { _ in }, inGame: actions)
            .background(Color(nsColor: .windowBackgroundColor))
        let host = NSHostingView(rootView: root)
        host.sizingOptions = []
        let w = min(600, parent.bounds.width - 32), h = min(720, parent.bounds.height - 32)
        host.frame = NSRect(x: (parent.bounds.width - w) / 2, y: (parent.bounds.height - h) / 2, width: w, height: h)
        host.autoresizingMask = [.minXMargin, .maxXMargin, .minYMargin, .maxYMargin]
        host.wantsLayer = true
        host.layer?.cornerRadius = 12; host.layer?.masksToBounds = true
        host.layer?.borderWidth = 1; host.layer?.borderColor = NSColor.separatorColor.cgColor
        parent.addSubview(host)
        view = host
        model.focus = nil
        log("open")
    }

    func close() {
        guard let v = view else { return }
        v.removeFromSuperview(); view = nil; model.focus = nil
        log("closed")
        front_settings_closed()
    }

    // The rows in the order the window shows them (basic first, then those under Advanced settings, which opens when the selection reaches them), without those an env file fixes
    private var order: [Setting] {
        let rows = model.sections(basic: true).flatMap { model.rows(in: $0, basic: true) } + model.sections(basic: false).flatMap { model.rows(in: $0, basic: false) }
        return rows.filter { !model.fixed.contains($0.env) }
    }
    private func select(_ s: Setting) {
        if !s.basic && !UserDefaults.standard.bool(forKey: "window.advanced") { UserDefaults.standard.set(true, forKey: "window.advanced") }   // LauncherView's @AppStorage opens it
        model.focus = s.env
    }

    // A controller or the arrow keys: 0 up, 1 down, 2 left, 3 right (the previous or next value), 4 A (a toggle flips, a choice takes its next value), 5 B (closes)
    func nav(_ code: Int) {
        if code == 5 { close(); return }
        let rows = order
        guard !rows.isEmpty else { return }
        let i = rows.firstIndex { $0.env == model.focus }
        switch code {
        case 0: select(rows[max(0, (i ?? rows.count) - 1)])
        case 1: select(rows[min(rows.count - 1, (i ?? -1) + 1)])
        case 2, 3, 4:
            guard let i else { select(rows[0]); return }
            step(rows[i], code == 2 ? -1 : 1, wrap: code == 4)
        default: break
        }
    }

    private func step(_ s: Setting, _ d: Int, wrap: Bool) {
        let now = model.values[s.env] ?? s.def
        switch s.kind {
        case "toggle": model.values[s.env] = wrap ? (now == s.onValue ? s.offValue : s.onValue) : (d > 0 ? s.onValue : s.offValue)
        case "choice":
            let o = s.options ?? []; guard !o.isEmpty else { return }
            let k = o.firstIndex { $0[0] == now } ?? 0
            let n = wrap ? (k + 1) % o.count : min(o.count - 1, max(0, k + d))
            model.values[s.env] = o[n][0]
        case "range":
            guard !wrap else { return }
            let st = s.step ?? 0.05, x = ((Double(now) ?? 0) + Double(d) * st)
            model.values[s.env] = String(format: "%.2f", min(s.max ?? 1, max(s.min ?? 0, x)))
        default: break
        }
    }

    // DM_CTL "menushot <path>": the window as drawn now, as a PNG (a check of its look without a screen capture)
    func snapshot(_ path: String) -> Bool {
        guard let v = view, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { log("[RED] menushot: the window is not open"); return false }
        v.cacheDisplay(in: v.bounds, to: rep)
        guard let png = rep.representation(using: .png, properties: [:]), (try? png.write(to: URL(fileURLWithPath: path))) != nil else { log("[RED] menushot: cannot write \(path)"); return false }
        log("menushot \(path)")
        return true
    }

    // DM_CTL "set <VAR>=<value>" (hle_hid.c): as a choice in the window, open or not
    func set(_ env: String, _ v: String) -> Bool {
        guard let s = model.settings.first(where: { $0.env == env }), s.accepts(v), !model.fixed.contains(env) else { log("[RED] set \(env)=\(v): not a setting of this list, fixed, or not a value it takes"); return false }
        model.values[env] = v
        return true
    }
}

// front_mac.m's calls, on the main thread. Open: 0 when this host has no settings list
@_cdecl("dm_settings_panel_open") public func dmSettingsPanelOpen(_ parent: UnsafeMutableRawPointer) -> Int32 {
    guard let g = GameSettings.load() else { return 0 }
    g.open(in: Unmanaged<NSView>.fromOpaque(parent).takeUnretainedValue())
    return 1
}
@_cdecl("dm_settings_panel_close") public func dmSettingsPanelClose() { GameSettings.shared?.close() }
@_cdecl("dm_settings_panel_is_open") public func dmSettingsPanelIsOpen() -> Int32 { GameSettings.shared?.isOpen == true ? 1 : 0 }
@_cdecl("dm_settings_panel_nav") public func dmSettingsPanelNav(_ code: Int32) { GameSettings.shared?.nav(Int(code)) }
@_cdecl("dm_settings_panel_snapshot") public func dmSettingsPanelSnapshot(_ path: UnsafePointer<CChar>) -> Int32 { GameSettings.shared?.snapshot(String(cString: path)) == true ? 1 : 0 }
@_cdecl("dm_settings_panel_set") public func dmSettingsPanelSet(_ env: UnsafePointer<CChar>, _ value: UnsafePointer<CChar>) -> Int32 {
    guard let g = GameSettings.load() else { return 0 }
    return g.set(String(cString: env), String(cString: value)) ? 1 : 0
}

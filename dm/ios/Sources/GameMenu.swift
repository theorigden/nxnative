// The in-game menu, opened by the gamepad's menu button at the top centre (DmGamepad.m): the controller layout, then the settings-screen settings the running game takes at once
// (front_ios.m dm_setting_live, then the host's settings_live.c: the tone map, AgX look and colour boost of a game with a host tone map, the frame rate of a frame step page), grouped as on the settings screen but without its headings, one row each, so the menu stays short over the game (its text size is fixed: front_ios.m
// startGame). A pick is saved as Play saves it (LauncherModel.choose), so the settings screen shows it at the next start; a setting an env file fixes is shown, not changed. Settings
// that need the next start (language, pipelines, the frame rate and so on), and the sliders, stay on the settings screen, which the menu's title points to; Render scale, a slider there,
// is offered here in steps of 0.1, as the game takes it at once (settings_live.c) and it is what to try when a frame rate does not hold.
import UIKit

var gameMenuModel: LauncherModel?   // the settings screen's model (Launcher.swift); nil in an app without one: the menu has the layout only

@_cdecl("dm_game_menu")
public func dmGameMenu() -> UnsafeMutableRawPointer {
    let title = gameMenuModel != nil ? "More settings on the start screen" : ""
    let menu = UIMenu(title: title, children: [UIDeferredMenuElement.uncached { done in done(gameMenuItems()) }])   // built each time it opens, so it shows the current choices
    return Unmanaged.passRetained(menu).toOpaque()
}

private func gameMenuItems() -> [UIMenuElement] {
    let names = ["2D", "3D", "Tap"]
    let layouts = (0..<3).filter { dm_pad_layout_offered(Int32($0)) }.map { l in
        UIAction(title: names[l], attributes: .keepsMenuPresented, state: dm_pad_layout() == l ? .on : .off) { _ in dm_pad_layout_set(Int32(l)) }
    }
    let layout = UIMenu(title: "Controller layout", options: .singleSelection, children: layouts)   // a choice's value shows in its submenu: a subtitle would make each row two lines
    var items: [UIMenuElement] = []
    var placed = false
    if let m = gameMenuModel {
        for section in m.sections {
            var rows: [UIMenuElement] = section == "Controls" ? [layout] : []
            if section == "Controls" { placed = true }
            for s in m.rows(in: section) where (s.kind == "choice" || s.kind == "toggle" || s.env == "DM_RENDER_SCALE") && dm_setting_live(s.env, nil) { rows.append(gameMenuRow(m, s)) }
            if !rows.isEmpty { items.append(UIMenu(options: .displayInline, children: rows)) }
        }
    }
    if !placed { items.insert(UIMenu(options: .displayInline, children: [layout]), at: 0) }
    if gameMenuModel != nil {   // the start screen's own choice (Launcher.swift quickStartKey): off brings the settings screen back at the next launch
        let quick = UserDefaults.standard.bool(forKey: quickStartKey)
        items.append(UIMenu(options: .displayInline, children: [UIAction(title: "Start straight into the game", attributes: .keepsMenuPresented, state: quick ? .on : .off) { _ in
            UserDefaults.standard.set(!quick, forKey: quickStartKey)
        }]))
    }
    return items
}

private func gameMenuRow(_ m: LauncherModel, _ s: Setting) -> UIMenuElement {
    let now = m.values[s.env] ?? s.def, fixed = m.fixed.contains(s.env)
    let attributes: UIMenuElement.Attributes = fixed ? .disabled : .keepsMenuPresented   // the menu stays open after a pick, for several adjustments in a row
    func pick(_ v: String) { m.choose(s, v); _ = dm_setting_live(s.env, v) }
    if s.kind == "toggle" {
        let a = UIAction(title: s.label, attributes: attributes, state: now == s.onValue ? .on : .off) { _ in pick(now == s.onValue ? s.offValue : s.onValue) }
        if fixed { a.subtitle = "Set in env.txt" }
        return a
    }
    if s.kind == "range" {   // Render scale: steps of 0.1 from the range's top down to its bottom (a slider does not fit a menu over the game), the current value marked when it is a step
        let lo = s.min ?? 0.5, hi = s.max ?? 1, v = Double(now) ?? hi
        let steps = stride(from: hi, through: lo - 0.001, by: -0.1).map { (round($0 * 100) / 100) }
        let actions = steps.map { x in UIAction(title: m.rangeLabel(s, x), attributes: attributes, state: abs(x - v) < 0.001 ? .on : .off) { _ in pick(String(format: "%.2f", x)) } }
        return UIMenu(title: s.label, subtitle: fixed ? "\(m.rangeLabel(s, v)), set in env.txt" : nil, options: .singleSelection, children: actions)
    }
    let options = offeredOptions(s, current: now)
    let current = options.first { $0[0] == now }?[1] ?? now
    let actions = options.map { o in UIAction(title: o[1], attributes: attributes, state: o[0] == now ? .on : .off) { _ in pick(o[0]) } }
    return UIMenu(title: s.label, subtitle: fixed ? "\(current), set in env.txt" : nil, options: .singleSelection, children: actions)
}

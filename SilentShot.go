// SilentShot — portable stitched multi-monitor screenshot tool
// Ctrl+Alt+E : capture all displays as ONE stitched PNG
// Ctrl+Alt+Q : quit
package main

import (
    "image"
    "image/draw"
    "image/png"
    "os"
    "path/filepath"
    "syscall"
    "time"

    "github.com/kbinani/screenshot"
    "golang.design/x/hotkey"
)

// captureSem is a 1-slot semaphore so a capture never overlaps itself.
var captureSem = make(chan struct{}, 1)

func setDPIAware() {
    // Per-monitor DPI awareness => full native resolution on scaled displays.
    // Both calls are harmless even if one fails.
    syscall.NewLazyDLL("shcore.dll").NewProc("SetProcessDpiAwareness").Call(2)
    syscall.NewLazyDLL("user32.dll").NewProc("SetProcessDPIAware").Call()
}

func captureStitched(outDir string) {
    select {
    case captureSem <- struct{}{}:
        defer func() { <-captureSem }()
    default:
        return // a capture is already running; ignore this key press
    }

    n := screenshot.NumActiveDisplays()
    if n == 0 {
        return
    }

    // Union of all display rectangles (handles negative coordinates
    // for monitors positioned left of/above the primary display).
    u := screenshot.GetDisplayBounds(0)
    for i := 1; i < n; i++ {
        u = u.Union(screenshot.GetDisplayBounds(i))
    }

    stitched := image.NewRGBA(image.Rect(0, 0, u.Dx(), u.Dy()))
    draw.Draw(stitched, stitched.Bounds(), image.Black, image.Point{}, draw.Src) // opaque black for gaps

    for i := 0; i < n; i++ {
        b := screenshot.GetDisplayBounds(i)
        disp, err := screenshot.CaptureRect(b)
        if err != nil {
            continue
        }
        draw.Draw(stitched, b.Sub(u.Min), disp, b.Min, draw.Src)
    }

    _ = os.MkdirAll(outDir, 0o755)
    name := filepath.Join(outDir, time.Now().Format("20060102_150405")+"_ALL.png")
    f, err := os.Create(name)
    if err != nil {
        return
    }
    defer f.Close()
    _ = png.Encode(f, stitched)
}

func main() {
    setDPIAware()

    exe, err := os.Executable()
    if err != nil {
        return
    }
    outDir := filepath.Join(filepath.Dir(exe), "captures")
    _ = os.MkdirAll(outDir, 0o755)

    hkCap := hotkey.New([]hotkey.Modifier{hotkey.ModCtrl, hotkey.ModAlt}, hotkey.KeyE)
    if err := hkCap.Register(); err != nil {
        return
    }
    hkQuit := hotkey.New([]hotkey.Modifier{hotkey.ModCtrl, hotkey.ModAlt}, hotkey.KeyQ)
    if err := hkQuit.Register(); err != nil {
        _ = hkCap.Unregister()
        return
    }

    for {
        select {
        case <-hkCap.Keydown():
            go captureStitched(outDir)
        case <-hkQuit.Keydown():
            _ = hkCap.Unregister()
            _ = hkQuit.Unregister()
            return
        }
    }
}
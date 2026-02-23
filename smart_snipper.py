import tkinter as tk
from PIL import ImageGrab
import os
import time
import keyboard
import ctypes # <--- NEW: REQUIRED FOR DPI FIX

# --- 1. FORCE DPI AWARENESS (THE FIX) ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# CONFIG
OUTPUT_FOLDER = "jee_smart_snips"
if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

class SmartSnipper:
    def __init__(self):
        self.root = tk.Tk()
        
        # Window Setup
        self.root.attributes('-alpha', 0.3)
        self.root.attributes('-fullscreen', True)
        self.root.attributes('-topmost', True)
        self.root.config(cursor="cross")
        
        # Canvas
        self.canvas = tk.Canvas(self.root, cursor="cross", bg="grey10")
        self.canvas.pack(fill="both", expand=True)
        
        # State
        self.current_q_num = 1
        self.mode = "question"
        self.is_hidden = False
        self.rect = None
        self.start_x = None
        
        # Inputs
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        # Global Toggle
        keyboard.add_hotkey('`', self.toggle_visibility, suppress=True)
        keyboard.add_hotkey('esc', self.quit_app)
        
        # Register keys initially
        self.keys_registered = False
        self.register_action_keys()
        
        # Label
        self.label = tk.Label(self.root, text=self.get_status_text(), 
                              font=("Arial", 14, "bold"), bg="white", fg="red")
        self.label.place(x=50, y=50)

        print("--- DPI-FIXED SNIPPER READY ---")
        self.root.mainloop()

    def get_status_text(self):
        return f"Q{self.current_q_num} : [{self.mode.upper()}] | Press ` to Scroll"

    def register_action_keys(self):
        if self.keys_registered: return
        keyboard.add_hotkey('q', lambda: self.set_mode("question"))
        keyboard.add_hotkey('a', lambda: self.set_mode("A"))
        keyboard.add_hotkey('b', lambda: self.set_mode("B"))
        keyboard.add_hotkey('c', lambda: self.set_mode("C"))
        keyboard.add_hotkey('d', lambda: self.set_mode("D"))
        keyboard.add_hotkey('n', self.next_question)
        self.keys_registered = True

    def unregister_action_keys(self):
        if not self.keys_registered: return
        try:
            keyboard.remove_hotkey('q')
            keyboard.remove_hotkey('a')
            keyboard.remove_hotkey('b')
            keyboard.remove_hotkey('c')
            keyboard.remove_hotkey('d')
            keyboard.remove_hotkey('n')
        except: pass
        self.keys_registered = False

    def toggle_visibility(self):
        if self.is_hidden:
            # SHOW
            self.root.deiconify()
            self.root.attributes('-fullscreen', True)
            self.root.attributes('-topmost', True)
            self.is_hidden = False
            self.register_action_keys()
        else:
            # HIDE
            self.root.withdraw()
            self.is_hidden = True
            self.unregister_action_keys()

    def quit_app(self):
        self.root.destroy()
        os._exit(0)

    def set_mode(self, mode):
        self.mode = mode
        self.label.config(text=self.get_status_text())

    def next_question(self):
        self.current_q_num += 1
        self.mode = "question"
        self.label.config(text=self.get_status_text())

    def on_press(self, event):
        self.start_x = self.root.winfo_pointerx()
        self.start_y = self.root.winfo_pointery()
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, 1, 1, outline='red', width=2)

    def on_drag(self, event):
        cur_x = self.root.winfo_pointerx()
        cur_y = self.root.winfo_pointery()
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)

    def on_release(self, event):
        if self.is_hidden: return
        
        x1, y1 = (self.start_x, self.start_y)
        x2 = self.root.winfo_pointerx()
        y2 = self.root.winfo_pointery()
        
        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            self.canvas.delete(self.rect)
            return

        x_start, x_end = sorted([x1, x2])
        y_start, y_end = sorted([y1, y2])
        
        self.root.withdraw()
        time.sleep(0.15)
        
        # Grab using EXACT screen coordinates
        img = ImageGrab.grab(bbox=(x_start, y_start, x_end, y_end), all_screens=True)
        
        filename = f"{OUTPUT_FOLDER}/Q{self.current_q_num}_{self.mode}.png"
        img.save(filename)
        print(f"  Saved: {filename}")
        
        self.root.deiconify()
        self.canvas.delete(self.rect)
        
        if self.mode == "question": self.set_mode("A")
        elif self.mode == "A": self.set_mode("B")
        elif self.mode == "B": self.set_mode("C")
        elif self.mode == "C": self.set_mode("D")
        elif self.mode == "D": self.next_question()

if __name__ == "__main__":
    SmartSnipper()
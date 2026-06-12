import tkinter as tk
import warnings
from gui import ScreenerApp

if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    root = tk.Tk()
    app = ScreenerApp(root)
    root.mainloop()

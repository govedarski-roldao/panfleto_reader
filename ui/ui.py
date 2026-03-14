import shutil
from backend.pdf_reader import remove_img_from_pdf
import webbrowser
from tkinter import *
from tkinter import filedialog
from tkinter import messagebox
import os
import zipfile
import threading
from datetime import datetime
from pathlib import Path
import subprocess
from tkinter.scrolledtext import ScrolledText
import sys

# pip install -r requirements.txt
# C:\Users\UI\Desktop\Python\Python310\python.exe "C:\UI_Guardians_AI_Automation\Guardians\create_ticket_ui.py"


# ---------------------------- CONSTANTS ------------------------------- #



# ---------------------------- FUNCTIONS ------------------------------- #

root = None
creator_var = None
bench_var = None
wm_var = None
test_bench_var = None
main_title_input = None
attachments_input = None
attached_count_label = None
log_text = None


class TextRedirector:
    def __init__(self, text_widget, tag):
        self.text_widget = text_widget
        self.tag = tag
        self._last_was_newline = False

    def write(self, message):
        if not message.strip():
            return
        self.text_widget.after(0, self._append, message)

    def _append(self, message):
        self.text_widget.config(state="normal")

        # garante que a mensagem termina com \n
        if not message.endswith("\n"):
            message += "\n"

        # adiciona UMA linha em branco extra
        message += "\n"

        self.text_widget.insert("end", message, self.tag)
        self.text_widget.see("end")
        self.text_widget.config(state="disabled")

    def flush(self):
        pass


def reset_fields():
    main_title_input.delete(0, END)
    attachments_input.delete(0, END)
    attached_count_label.config(text="Files attached: 0")
    main_title_input.focus()


def open_link(url):
    chrome_paths = [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        "/usr/bin/google-chrome",  # Linux
        "/usr/bin/google-chrome-stable",  # Linux alternative
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"  # macOS
    ]
    reset_fields()
    chrome_found = False
    for path in chrome_paths:
        if os.path.exists(path):
            webbrowser.get(f'"{path}" %s').open_new(url)
            chrome_found = True
            break

    if not chrome_found:
        # Fallback para navegador padrão
        webbrowser.open_new(url)


def check_creator():
    user = creator_var.get()
    print(f"Selected creator ID: {user}")
    print(f'Username: {os.getenv(f"JIRA_USERNAME_{user}")}')
    print(f'Token: {os.getenv(f"JIRA_TOKEN_{user}")}')


def browse_files():
    filenames = filedialog.askopenfilenames(
        title="Select files",
        filetypes=(
            ("All files", "*.*"),
            ("Text files", "*.txt"),
            ("Images", "*.png *.jpg *.jpeg *.gif"),
            ("PDFs", "*.pdf"),
            ("ZIP archives", "*.zip"),
            ("DLT files", "*.dlt"),
            ("Videos", "*.mp4 *.avi *.mov *.mkv")
        )
    )
    if filenames:
        attachments_input.delete(0, END)
        attachments_input.insert(0, "; ".join(filenames))

        # Update Counter
        attached_count_label.config(text=f"Files attached: {len(filenames)}")


def create_ticket_thread():
    pdf_path = attachments_input.get().strip()
    threading.Thread(target=remove_img_from_pdf, args=(pdf_path,), daemon=True).start()


def organize_files(files_to_organize):
    final_attachments = []

    main_title = files_to_organize["main_title"].lower()
    attachments_list = files_to_organize["attachments"]

    base_folder = Path(r"C:\Evidences\reported")
    base_folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_name = f"{timestamp}_{main_title.replace(' ', '_').replace('/', '_')}"

    target_folder = base_folder / folder_name
    target_folder.mkdir(parents=True, exist_ok=True)

    for f in attachments_list:
        src_path = Path(f)
        dest_path = target_folder / src_path.name

        counter = 1
        while dest_path.exists():
            dest_path = target_folder / f"{src_path.stem}({counter}){src_path.suffix}"
            counter += 1

        try:
            shutil.move(str(src_path), str(dest_path))
            print(f"Moved: {src_path} -> {dest_path}")
        except Exception as e:
            shutil.copy2(str(src_path), str(dest_path))
            print(f"Move failed ({e}), file copied: {src_path} -> {dest_path}")

        final_attachments.append(str(dest_path))

    return final_attachments


def verify_fields():
    polite = "Please, introduce the "
    errors = []
    files_to_send = []
    main_title = main_title_input.get().strip()
    attachments_str = attachments_input.get().strip()  # string do Entry
    bench = bench_var.get()

    attachments_list = []
    big_files = []
    print("CREATING TICKET, HOLD ON")

    if not attachments_str:
        errors.append("attachments")
    else:
        for file in attachments_str.split(";"):
            file = file.strip()
            if not os.path.exists(file):
                errors.append(f"attachment not found: {file}")
            else:
                file_size_kb = os.path.getsize(file) / 1024
                if file_size_kb > 90000:  # > 90MB
                    zip_path = file + ".zip"
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                        zipf.write(file, arcname=os.path.basename(file))
                    attachments_list.append(file)  # manter o ficheiro original
                    attachments_list.append(zip_path)  # adicionar o zip também
                    files_to_send.append(file)
                    files_to_send.append(zip_path)
                    big_files.append(file)
                else:
                    attachments_list.append(file)
                    files_to_send.append(file)

    if errors:
        messagebox.showwarning("Missing fields", polite + ", ".join(errors) + ".")
        return False

    return {
        "main_title": main_title,
        "creator": creator_var.get(),
        "attachments": attachments_list,  # ficheiros originais + zips
        "files_to_send": files_to_send,
        "wm": wm_var.get(),
        "bench": bench_var.get(),
    }


def run_ui():
    global root, creator_var, bench_var, wm_var, test_bench_var
    global main_title_input, attachments_input, attached_count_label, log_text

    root = Tk()
    root.title("Extractor de Precos")
    root.geometry("600x500")
    root.config(bg="#f5f5f5", padx=20, pady=20)
    root.option_add("*Font", ("Arial", 14))

    creator_var = StringVar()
    bench_var = StringVar()
    wm_var = StringVar()
    test_bench_var = StringVar(root)

    Label(root, text="Titulo para pasta final:", bg="#f5f5f5").grid(column=0, row=0, sticky="W", pady=5)
    Label(root, text="Escolhe o ficheiro PDF:", bg="#f5f5f5").grid(column=0, row=3, sticky="W", pady=5)

    attached_count_label = Label(root, text="Files attached: 0", bg="#f5f5f5")
    attached_count_label.grid(column=2, row=4, sticky="W", padx=10)

    main_title_input = Entry(root, width=40, bd=2, relief="groove")
    main_title_input.grid(column=1, row=0, columnspan=2, sticky="EW", padx=10, pady=5)
    main_title_input.focus()

    attachments_input = Entry(root, width=80, bd=2, relief="groove", font=("Arial", 10))
    attachments_input.grid(column=0, row=4, columnspan=2, sticky="EW", padx=10, pady=5)

    root.grid_columnconfigure(1, weight=1)

    browse_button = Button(
        text="Browse...",
        command=browse_files,
        bg="#007acc",
        fg="white",
        relief="raised",
        padx=10,
        pady=5,
    )
    browse_button.grid(column=2, row=3, padx=10, pady=5, sticky="E")

    create_ticket_button = Button(
        root,
        text="Extrair Precos",
        command=create_ticket_thread,
        bg="#28a745",
        fg="white",
        relief="raised",
        padx=15,
        pady=8,
    )
    create_ticket_button.grid(column=0, row=9, columnspan=3, pady=10, sticky="EW")

    log_frame = Frame(root, bg="black")
    log_frame.grid(column=0, row=11, columnspan=3, sticky="EW", padx=10, pady=10)

    log_text = ScrolledText(
        log_frame,
        width=70,
        height=10,
        bd=2,
        relief="sunken",
        font=("Consolas", 10),
        wrap="word",
        bg="black",
        fg="white",
        insertbackground="white",
    )
    log_text.pack(fill=BOTH, expand=True)
    log_text.insert("end", "Logs will appear here...\n")
    log_text.config(state="disabled")

    sys.stdout = TextRedirector(log_text, "STDOUT")
    sys.stderr = TextRedirector(log_text, "STDERR")

    root.grid_columnconfigure(1, weight=1)
    root.grid_columnconfigure(2, weight=0)
    root.mainloop()


if __name__ == "__main__":
    run_ui()

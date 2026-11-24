package in.zebjus.areion;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.util.Base64;
import android.widget.Toast;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.util.Locale;

/** Stage reasonably sized chunks privately before letting Android pick the destination. */
final class DocumentExport {
    static final int REQUEST = 6210;
    private static final int MAX_FILE = 24 * 1024 * 1024;
    private final Activity activity;
    private int sequence;
    private File file;
    private FileOutputStream buffer;
    private int total;
    private int written;
    private String name;
    private String mime;

    DocumentExport(Activity activity) { this.activity = activity; }

    synchronized int begin(String filename, int size) {
        if (file != null || filename == null || !filename.matches("[A-Za-z0-9._ -]{1,150}")
                || size < 0 || size > MAX_FILE) return 0;
        String extension = filename.substring(filename.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        switch (extension) {
            case "csv": mime = "text/csv"; break;
            case "json": mime = "application/json"; break;
            case "txt": mime = "text/plain"; break;
            case "zip": mime = "application/zip"; break;
            default: return 0;
        }
        try {
            file = File.createTempFile("areion-export-", ".tmp", activity.getCacheDir());
            buffer = new FileOutputStream(file);
        } catch (IOException e) {
            clear(); return 0;
        }
        sequence = sequence == Integer.MAX_VALUE ? 1 : sequence + 1;
        name = filename;
        total = size;
        written = 0;
        return sequence;
    }

    synchronized boolean append(int token, String encoded) {
        if (token != sequence || buffer == null || encoded == null || encoded.length() > 65536) return false;
        try {
            byte[] bytes = Base64.decode(encoded, Base64.NO_WRAP);
            if (written + bytes.length > total) { clear(); return false; }
            buffer.write(bytes);
            written += bytes.length;
            return true;
        } catch (IOException | IllegalArgumentException bad) { clear(); return false; }
    }

    synchronized boolean finish(int token) {
        if (token != sequence || buffer == null || written != total) return false;
        try { buffer.close(); buffer = null; } catch (IOException e) { clear(); return false; }
        Intent choose = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType(mime).putExtra(Intent.EXTRA_TITLE, name);
        activity.runOnUiThread(() -> {
            try { activity.startActivityForResult(choose, REQUEST); }
            catch (RuntimeException e) { clear(); toast("Unable to open the Android file picker."); }
        });
        return true;
    }

    synchronized void cancel(int token) {
        if (token == sequence && buffer != null) clear();
    }

    synchronized void selected(Uri dest) {
        if (file == null) return;
        if (dest == null || !"content".equals(dest.getScheme())) { clear(); return; }
        final File source = file;
        file = null;
        new Thread(() -> {
            try (FileInputStream in = new FileInputStream(source);
                 OutputStream out = activity.getContentResolver().openOutputStream(dest, "wt")) {
                if (out == null) throw new IOException();
                byte[] bytes = new byte[32768];
                for (int n; (n = in.read(bytes)) != -1; ) out.write(bytes, 0, n);
            } catch (IOException | RuntimeException e) {
                toast("File could not be saved."); return;
            } finally { source.delete(); }
            toast("File saved.");
        }, "areion-save-file").start();
    }

    synchronized void clear() {
        if (buffer != null) try { buffer.close(); } catch (IOException ignored) { }
        buffer = null;
        if (file != null) file.delete();
        file = null;
    }

    private void toast(String text) {
        activity.runOnUiThread(() -> Toast.makeText(activity, text, Toast.LENGTH_SHORT).show());
    }
}

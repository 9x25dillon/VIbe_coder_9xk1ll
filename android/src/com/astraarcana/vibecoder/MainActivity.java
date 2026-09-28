package com.astraarcana.vibecoder;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.window.OnBackInvokedDispatcher;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

/**
 * The whole native side of VibeCoder: one WebView, one origin, no network.
 *
 * <p>The browser build (web client, Pyodide, the vibecoder engine) ships as APK
 * assets and is served from {@code https://appassets.androidplatform.net/} by
 * {@link #serve}. A real https origin rather than {@code file://} because module
 * workers, IndexedDB and streaming WebAssembly compilation all need one. Every
 * request for any other host is refused, and the manifest does not ask for
 * INTERNET, so the page cannot load anything it did not bring.
 */
public class MainActivity extends Activity {

    static final String HOST = "appassets.androidplatform.net";
    static final String HOME = "https://" + HOST + "/index.html";

    /** The same policy tools/web/serve.py sends; see its docstring for why each part is there. */
    static final String CSP = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
            + "worker-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; "
            + "font-src 'self'; img-src 'self' data:; manifest-src 'self'; object-src 'none'; "
            + "base-uri 'self'; form-action 'none'";

    static final Map<String, String> TYPES = new HashMap<>();

    static {
        TYPES.put("html", "text/html");
        TYPES.put("js", "text/javascript");
        TYPES.put("mjs", "text/javascript");
        TYPES.put("css", "text/css");
        TYPES.put("json", "application/json");
        TYPES.put("webmanifest", "application/manifest+json");
        TYPES.put("wasm", "application/wasm");
        TYPES.put("zip", "application/zip");
        TYPES.put("woff2", "font/woff2");
        TYPES.put("svg", "image/svg+xml");
        TYPES.put("png", "image/png");
        TYPES.put("py", "text/plain");
        TYPES.put("txt", "text/plain");
    }

    private WebView web;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFF050507);
        web = new WebView(this);
        web.setBackgroundColor(0xFF050507);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        fitInsets(root);

        boolean debuggable = (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        WebView.setWebContentsDebuggingEnabled(debuggable);

        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSupportMultipleWindows(false);
        // The ASCII art is a character grid; system font scaling would break
        // it. The game has its own code-size setting instead.
        settings.setTextZoom(100);
        settings.setUserAgentString(settings.getUserAgentString() + " VibeCoderApp/" + version());

        web.setWebViewClient(new Client());
        if (Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::back);
        }
        web.loadUrl(HOME);
    }

    /**
     * Pad the WebView by the system bars and the keyboard.
     *
     * <p>From target SDK 35 the window is edge-to-edge whether asked or not, and
     * adjustResize no longer shrinks it for the keyboard. Padding by the larger
     * of the navigation bar and the IME is what keeps the editor's symbol row
     * sitting on top of the keyboard rather than under it.
     */
    private void fitInsets(View root) {
        if (Build.VERSION.SDK_INT < 30) {
            return; // the pre-edge-to-edge window resizes for the keyboard by itself
        }
        getWindow().setDecorFitsSystemWindows(false);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            Insets bars = insets.getInsets(
                    WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            Insets ime = insets.getInsets(WindowInsets.Type.ime());
            view.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, ime.bottom));
            return WindowInsets.CONSUMED;
        });
    }

    private String version() {
        try {
            PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
            return info.versionName;
        } catch (Exception e) {
            return "0";
        }
    }

    /**
     * One back path for the whole app: the page decides (close a sheet, leave a
     * level, retreat from a fight). At the root it answers false and the app
     * goes to the background rather than finishing, so Python stays warm.
     */
    private void back() {
        web.evaluateJavascript("window.vcBack ? window.vcBack() : false", value -> {
            if (!"true".equals(value)) {
                moveTaskToBack(true);
            }
        });
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        back();
    }

    @Override
    protected void onPause() {
        web.onPause();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
        }
        super.onDestroy();
    }

    /** Serve an asset under www/, or refuse. Never touches the network. */
    WebResourceResponse serve(Uri url) {
        if (!"https".equals(url.getScheme()) || !HOST.equals(url.getHost())) {
            return refuse(403, "Forbidden");
        }
        String path = url.getPath();
        if (path == null || path.isEmpty() || path.equals("/")) {
            path = "/index.html";
        }
        if (path.contains("..") || path.contains("//")) {
            return refuse(404, "Not Found");
        }
        String extension = path.substring(path.lastIndexOf('.') + 1);
        String type = TYPES.get(extension);
        if (type == null) {
            type = "application/octet-stream";
        }
        boolean text = type.startsWith("text/") || type.endsWith("json");
        try {
            InputStream body = getAssets().open("www" + path);
            return new WebResourceResponse(type, text ? "utf-8" : null, 200, "OK", headers(), body);
        } catch (IOException missing) {
            return refuse(404, "Not Found");
        }
    }

    private static Map<String, String> headers() {
        Map<String, String> headers = new HashMap<>();
        headers.put("Content-Security-Policy", CSP);
        headers.put("X-Content-Type-Options", "nosniff");
        headers.put("Referrer-Policy", "no-referrer");
        headers.put("Cache-Control", "no-cache");
        return headers;
    }

    private static WebResourceResponse refuse(int status, String reason) {
        return new WebResourceResponse("text/plain", "utf-8", status, reason, headers(),
                new ByteArrayInputStream(new byte[0]));
    }

    private final class Client extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            return serve(request.getUrl());
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri url = request.getUrl();
            if (HOST.equals(url.getHost())) {
                return false;
            }
            // A link out of the game opens in the browser, never in here.
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, url));
            } catch (Exception ignored) {
                // nothing can open it; stay put
            }
            return true;
        }

        @Override
        public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            // The renderer died (usually memory). Start clean rather than
            // leaving a dead view; progress is already on disk.
            recreate();
            return true;
        }
    }
}

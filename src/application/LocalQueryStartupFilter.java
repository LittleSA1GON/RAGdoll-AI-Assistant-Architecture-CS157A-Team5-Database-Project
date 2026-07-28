package application;

import java.io.File;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

import javax.servlet.Filter;
import javax.servlet.FilterChain;
import javax.servlet.FilterConfig;
import javax.servlet.ServletException;
import javax.servlet.ServletRequest;
import javax.servlet.ServletResponse;

// starts local model(s) if their not running
public class LocalQueryStartupFilter implements Filter {

    private static final Object PROCESS_LOCK = new Object();
    private static final Path LOCAL_QUERY_SCRIPT = Paths.get(
            "src", "rag_pipeline", "local_query.py"
    );
    private static final long STARTUP_TIMEOUT_MS = 45_000L;
    private static volatile Process localQueryProcess;

    private FilterConfig filterConfig;
    private Path projectRoot;
    private String healthUrl;

    @Override
    public void init(FilterConfig filterConfig) throws ServletException {
        this.filterConfig = filterConfig;
        projectRoot = resolveProjectRoot();
        healthUrl = getSetting(
                "RAGDOLL_API_HEALTH_URL",
                "ragdoll.apiHealthUrl",
                "http://127.0.0.1:8000/health"
        );
        log("RAGdoll local-query project root: " + projectRoot);
    }

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        try {
            ensureLocalQueryRunning();
        } catch (Exception error) {
            log("Unable to start the RAGdoll local model API automatically.", error);
        }
        chain.doFilter(request, response);
    }
    // runs queries from jsps
    private void ensureLocalQueryRunning() throws IOException, InterruptedException {
        if (isServiceHealthy()) {
            return;
        }

        synchronized (PROCESS_LOCK) {
            if (isServiceHealthy()) {
                return;
            }
            if (localQueryProcess != null && localQueryProcess.isAlive()) {
                waitForService(STARTUP_TIMEOUT_MS);
                return;
            }

            Path scriptPath = projectRoot.resolve(LOCAL_QUERY_SCRIPT);
            if (!Files.isRegularFile(scriptPath)) {
                throw new IOException("local_query.py was not found at " + scriptPath);
            }

            List<String> command = new ArrayList<>(findPythonCommand());
            command.add("-B");
            command.add(scriptPath.toString());

            Path logDirectory = projectRoot.resolve("logs");
            Files.createDirectories(logDirectory);
            File logFile = logDirectory.resolve("local_query.log").toFile();

            ProcessBuilder builder = new ProcessBuilder(command)
                    .directory(projectRoot.toFile())
                    .redirectErrorStream(true)
                    .redirectOutput(ProcessBuilder.Redirect.appendTo(logFile));
            builder.environment().put("PYTHONUNBUFFERED", "1");
            builder.environment().put("PYTHONDONTWRITEBYTECODE", "1");

            localQueryProcess = builder.start();
            log("Started RAGdoll local model API. Output: " + logFile.getAbsolutePath());
            waitForService(STARTUP_TIMEOUT_MS);
        }
    }

    private void waitForService(long timeoutMs) throws IOException, InterruptedException {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            if (isServiceHealthy()) {
                return;
            }
            if (localQueryProcess != null && !localQueryProcess.isAlive()) {
                throw new IOException(
                        "The local RAG API process exited with code "
                                + localQueryProcess.exitValue()
                                + ". Check logs/local_query.log."
                );
            }
            Thread.sleep(250L);
        }
        throw new IOException(
                "The local RAG API did not become healthy within "
                        + (timeoutMs / 1000L)
                        + " seconds. Check logs/local_query.log."
        );
    }

    private boolean isServiceHealthy() {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(healthUrl).openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(500);
            connection.setReadTimeout(500);
            connection.setUseCaches(false);
            return connection.getResponseCode() == HttpURLConnection.HTTP_OK;
        } catch (IOException ignored) {
            return false;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private List<String> findPythonCommand() throws IOException, InterruptedException {
        boolean windows = System.getProperty("os.name", "").toLowerCase().contains("win");
        List<List<String>> candidates = new ArrayList<>();

        String configuredPython = getSetting("RAGDOLL_PYTHON", "ragdoll.python", null);
        if (configuredPython != null) {
            candidates.add(List.of(configuredPython));
        }

        Path virtualEnvironmentPython = projectRoot.resolve(
                windows ? Paths.get(".venv", "Scripts", "python.exe")
                        : Paths.get(".venv", "bin", "python")
        );
        if (Files.isRegularFile(virtualEnvironmentPython)) {
            candidates.add(List.of(virtualEnvironmentPython.toString()));
        }

        candidates.add(windows ? List.of("py", "-3") : List.of("python3"));
        candidates.add(List.of("python"));

        for (List<String> candidate : candidates) {
            List<String> testCommand = new ArrayList<>(candidate);
            testCommand.add("--version");
            try {
                Process process = new ProcessBuilder(testCommand)
                        .redirectErrorStream(true)
                        .start();
                if (process.waitFor() == 0) {
                    return candidate;
                }
            } catch (IOException ignored) {
                // Try the next candidate.
            }
        }

        throw new IOException(
                "Python 3 was not found. Create a .venv in the project, set "
                        + "RAGDOLL_PYTHON, or make sure py, python3, or python is on PATH."
        );
    }

    private Path resolveProjectRoot() throws ServletException {
        String configuredRoot = getSetting(
                "RAGDOLL_PROJECT_ROOT", "ragdoll.projectRoot", null
        );
        if (configuredRoot != null) {
            Path configuredPath = normalizedPath(configuredRoot);
            if (containsLocalQuery(configuredPath)) {
                return configuredPath;
            }
            throw new ServletException(
                    "RAGDOLL_PROJECT_ROOT does not contain src/rag_pipeline/local_query.py: "
                            + configuredPath
            );
        }

        String realPath = filterConfig.getServletContext().getRealPath("/");
        if (realPath != null) {
            Path discovered = findProjectRoot(normalizedPath(realPath), 6);
            if (discovered != null) {
                return discovered;
            }
        }

        Path discovered = findProjectRoot(
                normalizedPath(System.getProperty("user.dir", ".")), 8
        );
        if (discovered != null) {
            return discovered;
        }

        throw new ServletException(
                "Could not locate src/rag_pipeline/local_query.py. Set the "
                        + "RAGDOLL_PROJECT_ROOT environment variable to the project folder."
        );
    }

    private Path findProjectRoot(Path start, int maximumParents) {
        Path current = start;
        for (int index = 0; current != null && index <= maximumParents; index++) {
            if (containsLocalQuery(current)) {
                return current;
            }
            current = current.getParent();
        }
        return null;
    }

    private boolean containsLocalQuery(Path directory) {
        return directory != null && Files.isRegularFile(directory.resolve(LOCAL_QUERY_SCRIPT));
    }

    private Path normalizedPath(String value) {
        return Paths.get(value).toAbsolutePath().normalize();
    }

    private String getSetting(String environmentName, String contextName, String defaultValue) {
        String value = nonBlank(System.getenv(environmentName));
        if (value != null) {
            return value;
        }
        value = filterConfig == null
                ? null
                : nonBlank(filterConfig.getServletContext().getInitParameter(contextName));
        return value == null ? defaultValue : value;
    }

    private String nonBlank(String value) {
        return value == null || value.trim().isEmpty() ? null : value.trim();
    }

    private void log(String message) {
        filterConfig.getServletContext().log(message);
    }

    private void log(String message, Throwable error) {
        filterConfig.getServletContext().log(message, error);
    }

    @Override
    public void destroy() {
        synchronized (PROCESS_LOCK) {
            if (localQueryProcess != null && localQueryProcess.isAlive()) {
                localQueryProcess.destroy();
            }
            localQueryProcess = null;
        }
    }
}
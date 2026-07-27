package application;

import java.io.File;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import javax.servlet.Filter;
import javax.servlet.FilterChain;
import javax.servlet.FilterConfig;
import javax.servlet.ServletException;
import javax.servlet.ServletRequest;
import javax.servlet.ServletResponse;

/**
 * Starts the local Python model API when the dashboard or admin page is requested.
 * Only one process is started for this deployed web application.
 */
public class LocalQueryStartupFilter implements Filter {

    private static final Object PROCESS_LOCK = new Object();
    private static volatile Process localQueryProcess;

    private FilterConfig filterConfig;
    private Path projectRoot;
    private String healthUrl;

    @Override
    public void init(FilterConfig filterConfig) throws ServletException {
        this.filterConfig = filterConfig;
        this.projectRoot = resolveProjectRoot(filterConfig);
        this.healthUrl = getSetting(
                "RAGDOLL_API_HEALTH_URL",
                "ragdoll.apiHealthUrl",
                "http://127.0.0.1:8000/health"
        );

        filterConfig.getServletContext().log(
                "RAGdoll local-query project root: " + projectRoot.toString()
        );
    }

    @Override
    public void doFilter(
            ServletRequest request,
            ServletResponse response,
            FilterChain chain
    ) throws IOException, ServletException {

        try {
            ensureLocalQueryRunning();
        } catch (Exception error) {
            /*
             * Allow the JSP page to load even if Python fails to start.
             * The page will display a connection error to the user.
             */
            filterConfig.getServletContext().log(
                    "Unable to start the RAGdoll local model API automatically.",
                    error
            );
        }

        chain.doFilter(request, response);
    }

    private void ensureLocalQueryRunning()
            throws IOException, InterruptedException {

        if (isServiceHealthy()) {
            return;
        }

        synchronized (PROCESS_LOCK) {
            if (isServiceHealthy()) {
                return;
            }

            if (localQueryProcess != null && localQueryProcess.isAlive()) {
                waitForService(45000L);
                return;
            }

            Path scriptPath = projectRoot
                    .resolve("src")
                    .resolve("rag_pipeline")
                    .resolve("local_query.py");

            if (!Files.isRegularFile(scriptPath)) {
                throw new IOException(
                        "local_query.py was not found at " + scriptPath
                );
            }

            List<String> command =
                    new ArrayList<String>(findPythonCommand());

            // -B prevents Python from creating __pycache__ directories or .pyc files.
            command.add("-B");
            command.add(scriptPath.toString());

            Path logDirectory = projectRoot.resolve("logs");
            Files.createDirectories(logDirectory);

            File logFile = logDirectory
                    .resolve("local_query.log")
                    .toFile();

            ProcessBuilder processBuilder = new ProcessBuilder(command);

            processBuilder.directory(projectRoot.toFile());
            processBuilder.redirectErrorStream(true);
            processBuilder.redirectOutput(
                    ProcessBuilder.Redirect.appendTo(logFile)
            );

            processBuilder.environment().put(
                    "PYTHONUNBUFFERED",
                    "1"
            );
            processBuilder.environment().put(
                    "PYTHONDONTWRITEBYTECODE",
                    "1"
            );

            localQueryProcess = processBuilder.start();

            filterConfig.getServletContext().log(
                    "Started RAGdoll local model API. Output: "
                            + logFile.getAbsolutePath()
            );

            waitForService(45000L);
        }
    }

    private void waitForService(long timeoutMilliseconds)
            throws IOException, InterruptedException {

        long deadline = System.currentTimeMillis() + timeoutMilliseconds;

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
                        + (timeoutMilliseconds / 1000L)
                        + " seconds. Check logs/local_query.log."
        );
    }

    private boolean isServiceHealthy() {
        HttpURLConnection connection = null;

        try {
            connection = (HttpURLConnection)
                    new URL(healthUrl).openConnection();

            connection.setRequestMethod("GET");
            connection.setConnectTimeout(500);
            connection.setReadTimeout(500);
            connection.setUseCaches(false);

            return connection.getResponseCode()
                    == HttpURLConnection.HTTP_OK;

        } catch (IOException ignored) {
            return false;

        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private List<String> findPythonCommand()
            throws IOException, InterruptedException {

        boolean windows = System.getProperty("os.name", "")
                .toLowerCase()
                .contains("win");

        List<List<String>> candidates =
                new ArrayList<List<String>>();

        String configuredPython = getSetting(
                "RAGDOLL_PYTHON",
                "ragdoll.python",
                null
        );

        if (configuredPython != null
                && !configuredPython.trim().isEmpty()) {
            candidates.add(Arrays.asList(configuredPython));
        }

        Path virtualEnvironmentPython = windows
                ? projectRoot.resolve(".venv").resolve("Scripts").resolve("python.exe")
                : projectRoot.resolve(".venv").resolve("bin").resolve("python");

        if (Files.isRegularFile(virtualEnvironmentPython)) {
            candidates.add(Arrays.asList(virtualEnvironmentPython.toString()));
        }

        if (windows) {
            candidates.add(Arrays.asList("py", "-3"));
            candidates.add(Arrays.asList("python"));
        } else {
            candidates.add(Arrays.asList("python3"));
            candidates.add(Arrays.asList("python"));
        }

        for (List<String> candidate : candidates) {
            List<String> testCommand =
                    new ArrayList<String>(candidate);

            testCommand.add("--version");

            try {
                Process testProcess =
                        new ProcessBuilder(testCommand)
                                .redirectErrorStream(true)
                                .start();

                int exitCode = testProcess.waitFor();

                if (exitCode == 0) {
                    return candidate;
                }

            } catch (IOException ignored) {
                // Try the next Python command.
            }
        }

        throw new IOException(
                "Python 3 was not found. Create a .venv in the project, "
                        + "set RAGDOLL_PYTHON, or make sure py, python3, "
                        + "or python is on PATH."
        );
    }

    private Path resolveProjectRoot(FilterConfig config)
            throws ServletException {

        String configuredRoot = getSetting(
                "RAGDOLL_PROJECT_ROOT",
                "ragdoll.projectRoot",
                null
        );

        if (configuredRoot != null
                && !configuredRoot.trim().isEmpty()) {

            Path configuredPath = Paths
                    .get(configuredRoot)
                    .toAbsolutePath()
                    .normalize();

            if (containsLocalQuery(configuredPath)) {
                return configuredPath;
            }

            throw new ServletException(
                    "RAGDOLL_PROJECT_ROOT does not contain "
                            + "src/rag_pipeline/local_query.py: "
                            + configuredPath
            );
        }

        String realPath =
                config.getServletContext().getRealPath("/");

        if (realPath != null) {
            Path discovered = findProjectRoot(
                    Paths.get(realPath)
                            .toAbsolutePath()
                            .normalize(),
                    6
            );

            if (discovered != null) {
                return discovered;
            }
        }

        Path workingDirectory = Paths
                .get(System.getProperty("user.dir", "."))
                .toAbsolutePath()
                .normalize();

        Path discovered = findProjectRoot(
                workingDirectory,
                8
        );

        if (discovered != null) {
            return discovered;
        }

        throw new ServletException(
                "Could not locate src/rag_pipeline/local_query.py. "
                        + "Set the RAGDOLL_PROJECT_ROOT environment "
                        + "variable to the project folder."
        );
    }

    private Path findProjectRoot(
            Path start,
            int maximumParents
    ) {
        Path current = start;

        for (int index = 0;
             current != null && index <= maximumParents;
             index++) {

            if (containsLocalQuery(current)) {
                return current;
            }

            current = current.getParent();
        }

        return null;
    }

    private boolean containsLocalQuery(Path directory) {
        return directory != null
                && Files.isRegularFile(
                        directory
                                .resolve("src")
                                .resolve("rag_pipeline")
                                .resolve("local_query.py")
                );
    }

    private String getSetting(
            String environmentName,
            String contextName,
            String defaultValue
    ) {
        String environmentValue =
                System.getenv(environmentName);

        if (environmentValue != null
                && !environmentValue.trim().isEmpty()) {

            return environmentValue.trim();
        }

        String contextValue = filterConfig == null
                ? null
                : filterConfig
                        .getServletContext()
                        .getInitParameter(contextName);

        if (contextValue != null
                && !contextValue.trim().isEmpty()) {

            return contextValue.trim();
        }

        return defaultValue;
    }

    @Override
    public void destroy() {
        synchronized (PROCESS_LOCK) {
            if (localQueryProcess != null
                    && localQueryProcess.isAlive()) {

                localQueryProcess.destroy();
            }

            localQueryProcess = null;
        }
    }
}
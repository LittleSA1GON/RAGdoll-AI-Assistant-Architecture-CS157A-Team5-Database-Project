package application;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import javax.servlet.Filter;
import javax.servlet.FilterChain;
import javax.servlet.FilterConfig;
import javax.servlet.ServletException;
import javax.servlet.ServletRequest;
import javax.servlet.ServletResponse;

/** Initializes the private Python worker used by the Java API. */
public final class LocalQueryStartupFilter implements Filter
{
    private FilterConfig filterConfig;

    @Override
    public void init(FilterConfig config) throws ServletException
    {
        filterConfig = config;
        Config.setProjectRoot(resolveProjectRoot());
    }

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain) throws IOException, ServletException
    {
        try
        {
            AppServices.PYTHON.status();
        }
        catch (Exception error)
        {
            filterConfig.getServletContext().log("Unable to start the RAGdoll model worker.", error);
        }
        chain.doFilter(request, response);
    }

    @Override
    public void destroy()
    {
        AppServices.PYTHON.close();
    }

    private Path resolveProjectRoot() throws ServletException
    {
        String configured = System.getenv("RAGDOLL_PROJECT_ROOT");
        if (configured != null && !configured.isBlank())
        {
            return requireProjectRoot(Paths.get(configured));
        }
        String realPath = filterConfig.getServletContext().getRealPath("/");
        if (realPath != null)
        {
            Path webRoot = Paths.get(realPath).toAbsolutePath().normalize();
            for (Path current = webRoot; current != null; current = current.getParent())
            {
                if (Files.isRegularFile(current.resolve("src/rag_pipeline/model_worker.py")))
                {
                    return current;
                }
            }
        }
        Path current = Paths.get(System.getProperty("user.dir", ".")).toAbsolutePath();
        while (current != null)
        {
            if (Files.isRegularFile(current.resolve("src/rag_pipeline/model_worker.py")))
            {
                return current;
            }
            current = current.getParent();
        }
        throw new ServletException("Project root not found. Set RAGDOLL_PROJECT_ROOT.");
    }

    private Path requireProjectRoot(Path candidate) throws ServletException
    {
        Path root = candidate.toAbsolutePath().normalize();
        if (!Files.isRegularFile(root.resolve("src/rag_pipeline/model_worker.py")))
        {
            throw new ServletException("model_worker.py was not found under " + root);
        }
        return root;
    }
}

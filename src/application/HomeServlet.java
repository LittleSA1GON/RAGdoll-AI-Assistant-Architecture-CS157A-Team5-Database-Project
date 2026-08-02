package application;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

/** Loads the landing page model list through the same Java model repository. */
public final class HomeServlet extends HttpServlet
{
    private static final long serialVersionUID = 1L;

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response) throws ServletException, IOException
    {
        Map<String, Object> discovery = AppServices.MODELS.discover();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> found = (List<Map<String, Object>>) discovery.get("models");
        List<String[]> models = new ArrayList<>();
        for (Map<String, Object> model : found)
        {
            models.add(
                    new String[] { String.valueOf(model.get("model_id")), String.valueOf(model.get("model_name")), String.valueOf(model.get("model_path")) });
        }
        request.setAttribute("models", models);
        request.setAttribute("status", Boolean.TRUE.equals(discovery.get("database_connected")) ? "Database connected successfully."
                : "Model files loaded; database unavailable: " + discovery.get("database_error"));
        request.getRequestDispatcher("/index.jsp").forward(request, response);
    }
}

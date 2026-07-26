package application;

import java.sql.Driver;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Enumeration;

import javax.servlet.ServletContextEvent;
import javax.servlet.ServletContextListener;

import com.mysql.cj.jdbc.AbandonedConnectionCleanupThread;

/**
 * Releases MySQL Connector/J resources when Tomcat stops or redeploys
 * this web application.
 */
public class MySqlCleanupListener implements ServletContextListener {

    @Override
    public void contextInitialized(ServletContextEvent event) {
        // No startup work is required.
    }

    @Override
    public void contextDestroyed(ServletContextEvent event) {
        try {
            AbandonedConnectionCleanupThread.checkedShutdown();
        } catch (RuntimeException error) {
            event.getServletContext().log(
                    "Unable to stop the MySQL abandoned-connection cleanup thread.",
                    error
            );
        }

        ClassLoader applicationClassLoader = getClass().getClassLoader();
        Enumeration<Driver> drivers = DriverManager.getDrivers();

        while (drivers.hasMoreElements()) {
            Driver driver = drivers.nextElement();

            if (driver.getClass().getClassLoader() != applicationClassLoader) {
                continue;
            }

            try {
                DriverManager.deregisterDriver(driver);
            } catch (SQLException error) {
                event.getServletContext().log(
                        "Unable to deregister JDBC driver "
                                + driver.getClass().getName()
                                + ".",
                        error
                );
            }
        }
    }
}
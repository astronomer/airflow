import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

public class TaskRunner {
    private static final Logger logger = LogManager.getLogger(TaskRunner.class);
    private static final ExecutorService threadPool = Executors.newFixedThreadPool(4);

    private final String dagID;
    private final String dagRunID;
    private final String taskName;
    private final TaskRegistry registry;

    private final String xcomPath;
    private final String varsPath;

    public TaskRunner(String dagID, String dagRunID, String taskName, TaskRegistry registry) {
        this.dagID = dagID;
        this.dagRunID = dagRunID;
        this.taskName = taskName;
        this.registry = registry;

        this.xcomPath = String.format("xcom_%s_%s.json", dagID, dagRunID);
        this.varsPath = String.format("vars_%s_%s.json", dagID, dagRunID);
    }

    public void runTask() {
        threadPool.submit(() -> {
            try {
                logger.info("Running task [{}] in DAG [{}] with run ID [{}]", taskName, dagID, dagRunID);

                XcomData xcom = XcomData.fromFile(xcomPath);
                Variables vars = Variables.fromFile(varsPath);

                InputContext ctx = new InputContext(xcom, vars);
                XcomData result = registry.execTask(dagID, taskName, ctx);

                result.writeToFile(xcomPath);
                logger.info("Task [{}] completed. Output Xcom written to [{}]", taskName, xcomPath);

            } catch (IOException e) {
                logger.error("Error running task [{}] in DAG [{}]: {}", taskName, dagID, e.getMessage(), e);
            }
        });
    }

    public static void shutdown() {
        threadPool.shutdown();
    }
}


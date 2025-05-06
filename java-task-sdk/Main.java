import java.io.File;
import java.io.IOException;
import java.time.Duration;
import java.time.Instant;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.json.JSONObject;

public class Main {
    private static final Logger logger = LogManager.getLogger(Main.class);

    public static void main(String[] args) throws IOException {
        TaskRegistry registry = new TaskRegistry();

        // Register tasks...

        // Hello DAG
        registry.registerTask("hello_dag", "hello", (inputCtx, taskName) -> {
            System.out.println("Hello, world\n");
            return new XcomData();
        });

        // Tutorial DAG: extract → transform → load
        registry.registerTask("tutorial_dag", "extract", (inputCtx, taskName) -> {
            String dataString = "{\"1001\": 301.27, \"1002\": 433.21, \"1003\": 502.22}";
            XcomData output = new XcomData();
            output.put("order_data", dataString);
            return output;
        });

        registry.registerTask("tutorial_dag", "transform", (inputCtx, taskName) -> {
            String extractDataString = inputCtx.getXcom("order_data");
            JSONObject orderData = new JSONObject(extractDataString);

            double totalOrderValue = 0.0;
            for (String key : orderData.keySet()) {
                totalOrderValue += orderData.getDouble(key);
            }

            JSONObject totalValue = new JSONObject();
            totalValue.put("total_order_value", totalOrderValue);

            XcomData output = new XcomData();
            output.put("total_order_value", totalValue.toString());
            return output;
        });

        registry.registerTask("tutorial_dag", "load", (inputCtx, taskName) -> {
            String totalValueString = inputCtx.getXcom("total_order_value");
            JSONObject totalOrderValue = new JSONObject(totalValueString);
            System.out.println("Loaded total order value: " + totalOrderValue.toString());
            return new XcomData();
        });

        try {
            // Hello task
            new TaskRunner("hello_dag", "run001", "hello", registry).runTask();
            waitForFile("xcom_hello_dag_run001.json");

            // Extract
            new TaskRunner("tutorial_dag", "run002", "extract", registry).runTask();
            waitForFile("xcom_tutorial_dag_run002.json");

            // Transform
            new TaskRunner("tutorial_dag", "run002", "transform", registry).runTask();
            waitForFile("xcom_tutorial_dag_run002.json");

            // Load
            new TaskRunner("tutorial_dag", "run002", "load", registry).runTask();
            waitForFile("xcom_tutorial_dag_run002.json");

        } catch (Exception e) {
            logger.error("Error executing DAG tasks: {}", e.getMessage(), e);
        } finally {
            TaskRunner.shutdown();
        }
    }

    // Polls until the file exists (with timeout)
    private static void waitForFile(String fileName) throws InterruptedException {
        File file = new File(fileName);
        Instant start = Instant.now();
        while (!file.exists()) {
            if (Duration.between(start, Instant.now()).getSeconds() > 10) {
                throw new RuntimeException("Timeout waiting for file: " + fileName);
            }
            Thread.sleep(200);
        }
    }
}


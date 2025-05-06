import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.function.BiFunction;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

//
// TaskRegistry
//
// Helper class which contains the list of Tasks which can be performed
// This includes a way to "register" the available Tasks and then to execute them
//
// Currently supported Tasks are: Hello
//

public class TaskRegistry {

    // set up a logging mechanism
    private static final Logger logger = LogManager.getLogger(TaskRegistry.class);

    // set up a private registry structure
    private final Map<String, Map<String, BiFunction<InputContext, String, XcomData>>> functionMap;

    public TaskRegistry() {
        this.functionMap = new HashMap<>();
        logger.info("TaskRegistry initialized");
    }

    public void registerTask(String dagID, String taskName, BiFunction<InputContext, String, XcomData> function) {
        functionMap.computeIfAbsent(dagID, k -> new HashMap<>()).put(taskName, function);
 
        logger.info("Registered function for task [{}] in DAG [{}]", taskName, dagID);
    }

    public XcomData execTask(String dagID, String taskName, InputContext inputContext) throws IOException {
        logger.debug("Getting configuration for task [{}] in DAG [{}]", taskName, dagID);

        Map<String, BiFunction<InputContext, String, XcomData>> taskMap = functionMap.get(dagID);
        if (taskMap == null) {
            logger.error("No tasks found for DAG ID [{}]", dagID);
            throw new IOException("No tasks registered for DAG ID: " + dagID);
        }

        BiFunction<InputContext, String, XcomData> function = taskMap.get(taskName);
        if (function == null) {
            logger.error("No task [{}] found in DAG [{}]", taskName, dagID);
            throw new IOException("No task found with name: " + taskName + " in DAG ID: " + dagID);
        }

        logger.info("Executing task [{}] in DAG [{}]", taskName, dagID);
        XcomData result = function.apply(inputContext, taskName);
        logger.debug("Task [{}] in DAG [{}] returned result: {}", taskName, dagID, result);
        return result;
    }
}


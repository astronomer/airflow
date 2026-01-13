module.exports = function(eleventyConfig) {
  // Copy static assets
  eleventyConfig.addPassthroughCopy("src/assets");
  eleventyConfig.addPassthroughCopy("src/css");
  eleventyConfig.addPassthroughCopy("src/js");

  // Copy public directory contents to root of output
  eleventyConfig.addPassthroughCopy({ "public": "/" });

  // Watch CSS and JS for changes
  eleventyConfig.addWatchTarget("src/css/");
  eleventyConfig.addWatchTarget("src/js/");

  // Add filters
  eleventyConfig.addFilter("slice", (array, start, end) => {
    return array.slice(start, end);
  });

  eleventyConfig.addFilter("formatDownloads", (num) => {
    if (!num) return "0";

    // For billions
    if (num >= 1_000_000_000) {
      const billions = num / 1_000_000_000;
      return billions >= 10 ? `${Math.round(billions)}B` : `${billions.toFixed(1)}B`;
    }

    // For millions
    if (num >= 1_000_000) {
      const millions = num / 1_000_000;
      return millions >= 10 ? `${Math.round(millions)}M` : `${millions.toFixed(1)}M`;
    }

    // For thousands
    if (num >= 1_000) {
      const thousands = num / 1_000;
      return thousands >= 10 ? `${Math.round(thousands)}K` : `${thousands.toFixed(1)}K`;
    }

    return num.toString();
  });

  eleventyConfig.addFilter("formatLargeNumber", (num) => {
    if (!num) return "0";
    if (num >= 1_000_000_000) return `${(num / 1_000_000_000).toFixed(1)}B`;
    if (num >= 1_000_000) return `${Math.round(num / 1_000_000)}M`;
    if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
    return num.toLocaleString();
  });

  eleventyConfig.addFilter("thousands", (num) => {
    if (!num && num !== 0) return "0";
    return num.toLocaleString();
  });

  eleventyConfig.addFilter("capitalize", (str) => {
    if (!str) return "";
    return str.charAt(0).toUpperCase() + str.slice(1);
  });

  eleventyConfig.addFilter("first", (str) => {
    if (!str) return "";
    return str.charAt(0);
  });

  return {
    dir: {
      input: "src",
      output: "_site",
      includes: "_includes",
      data: "_data"
    },
    templateFormats: ["njk", "md", "html"],
    htmlTemplateEngine: "njk",
    markdownTemplateEngine: "njk"
  };
};

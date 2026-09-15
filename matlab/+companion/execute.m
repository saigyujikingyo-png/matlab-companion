function receipt = execute(requestPath)
%EXECUTE Run a validated, owned job and always attempt an atomic receipt.
% The Python coordinator validates provenance, schema, paths and ownership.
request = jsondecode(fileread(requestPath));
jobDir = fileparts(request.output_dir);
receipt = struct('contract_version', '1.0', 'job_id', request.job_id, ...
    'operation', request.operation, 'state', 'failed', 'observed_at', '', ...
    'matlab_version', version, 'matlab_release', version('-release'), ...
    'summary', '', 'metrics', {{}}, 'artifacts', {{}}, ...
    'verification', struct('native_reopen', false, 'numerical', false, 'script_rerun', false), ...
    'details', [], 'error', []);
try
    checkCancellation(request);
    if ~isfolder(request.output_dir), mkdir(request.output_dir); end
    if ~isempty(dir(fullfile(request.output_dir, '*')))
        listing = dir(request.output_dir);
        if any(~ismember({listing.name}, {'.', '..'}))
            error('Companion:INPUT_INVALID', 'The owned output folder must be empty before a new execution.');
        end
    end
    cleanRequest = struct('operation', request.operation, 'parameters', request.parameters, ...
        'input_path', '', 'output_dir', '', 'cancel_path', '');
    if ~isempty(request.input_path)
        [~, ~, inputExtension] = fileparts(request.input_path);
        inputExtension = lower(inputExtension);
        if ~ismember(inputExtension, {'.csv', '.tsv'})
            error('Companion:INPUT_INVALID', 'Only staged CSV or TSV input is supported.');
        end
        inputName = ['input' inputExtension];
        copyfile(request.input_path, fullfile(request.output_dir, inputName));
        cleanRequest.input_path = inputName;
    end
    if strcmp(request.operation, 'revise_figure')
        copyfile(request.parameters.source_figure, fullfile(request.output_dir, 'source.fig'));
        cleanRequest.parameters.source_figure = 'source.fig';
    end
    computed = companion.run_recipe(request, request.output_dir);
    receipt.details = computed.details;
    receipt.metrics = computed.metrics;
    receipt.summary = computed.summary;
    receipt.verification.numerical = computed.numerical;
    method = struct('recipe_version', '1.0', 'operation', request.operation, ...
        'matlab_version', version, 'matlab_release', version('-release'), ...
        'request', cleanRequest, 'details', computed.details, 'metrics', {computed.metrics}, ...
        'input_policy', 'Original input bytes retained; no automatic row removal or unit conversion.', ...
        'scientific_assumptions', assumptions(request.operation), ...
        'reproduction', 'Run reproduce.m in MATLAB. Optional companion_output_dir selects a new output folder; default is ./reproduced.');
    if strcmp(request.operation, 'data_profile')
        method.reproduction = 'Reopen analysis.mat to inspect the imported table and profile; script reproduction is not applicable to this operation.';
    end
    writeJson(fullfile(request.output_dir, 'method.json'), method);
    checkCancellation(request);
    verifyNative(request.output_dir, computed.has_figure);
    receipt.verification.native_reopen = true;
    if ~strcmp(request.operation, 'data_profile')
        writeReproduction(request.output_dir);
        checkCancellation(request);
        rerunDir = fullfile(jobDir, 'verification', 'reproduced');
        rerun = isolatedRerun(fullfile(request.output_dir, 'reproduce.m'), rerunDir, request.cancel_path);
        if ~isequaln(rerun.details, computed.details)
            error('Companion:NATIVE_VERIFY_FAILED', 'Reproduction changed operation results.');
        end
        compareNative(request.output_dir, rerunDir);
        receipt.verification.script_rerun = true;
    end
    checkCancellation(request);
    receipt.state = 'completed';
catch exception
    receipt.state = 'failed';
    code = 'NATIVE_EXECUTION_FAILED';
    message = 'Native execution failed. Partial artifacts are retained for recovery.';
    if startsWith(exception.identifier, 'Companion:')
        code = extractAfter(exception.identifier, 'Companion:');
        message = exception.message;
    end
    if strcmp(code, 'CANCELLED')
        receipt.state = 'cancelled';
        message = 'Cancellation was observed; MATLAB recipe execution has stopped at a safe boundary.';
    end
    receipt.summary = message;
    receipt.error = struct('code', char(code), 'message', message);
    receipt.details = [];
end
receipt.artifacts = artifactInventory(request.output_dir);
receipt.observed_at = char(datetime('now', 'TimeZone', 'UTC', 'Format', "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"));
% jsonencode represents empty numeric arrays as []; the public seam uses null.
encoded = jsonencode(receipt, 'ConvertInfAndNaN', true);
encoded = strrep(encoded, '"details":[]', '"details":null');
encoded = strrep(encoded, '"error":[]', '"error":null');
temporary = fullfile(jobDir, ['receipt-' char(java.util.UUID.randomUUID) '.tmp']);
writeText(temporary, encoded);
[moved, ~] = movefile(temporary, fullfile(jobDir, 'receipt.json'), 'f');
if ~moved
    error('Companion:NATIVE_EXECUTION_FAILED', 'The completion receipt could not be committed.');
end
end

function checkCancellation(request)
if ~isempty(request.cancel_path) && isfile(request.cancel_path)
    error('Companion:CANCELLED', 'Cancellation observed before the next safe workflow step.');
end
end

function value = assumptions(operation)
switch operation
    case 'linear_calibration'
        value = ['Model y = slope*x + intercept. Known-sigma columns contain independent known y standard deviations; effective weight is 1/sigma^2. ' ...
            'Relative-weight columns contain direct positive weights; covariance is scaled by weighted residual sum of squares / residual degrees of freedom. ' ...
            'Only y uncertainty is modelled; x uncertainty, correlated errors, confidence intervals and inverse prediction are not calculated. ' ...
            'R-squared is centered for free intercept and uncentered for zero intercept. A fixed zero intercept has standard error zero when uncertainty is otherwise available.'];
    case 'first_order_kinetics'
        value = 'First-order irreversible decay dc/dt=-k*c, rate constant in reciprocal declared time units. ode45 with NonNegative=1 and deval on the requested grid is checked against c0*exp(-k*t). Values are simulations, not measurements.';
    case 'revise_figure'
        value = 'Only trusted plugin-created figures are accepted. Requested presentation changes retain all numeric line data.';
    otherwise
        value = 'No statistical model, uncertainty, row deletion or unit conversion is inferred.';
end
end

function writeReproduction(outputDir)
source = fileread(fullfile(fileparts(mfilename('fullpath')), 'run_recipe.m'));
header = [ ...
    "%% Reproduce this MATLAB Companion result using base MATLAB." newline ...
    "% Keep this script with method.json and input.csv/input.tsv/source.fig when present." newline ...
    "% Output defaults to a separate reproduced folder; source artifacts are retained." newline ...
    "companion_bundle_dir = fileparts(mfilename('fullpath'));" newline ...
    "if ~exist('companion_output_dir', 'var') || isempty(companion_output_dir)" newline ...
    "    companion_output_dir = fullfile(companion_bundle_dir, 'reproduced');" newline ...
    "end" newline ...
    "if strcmp(char(java.io.File(companion_output_dir).getCanonicalPath()), char(java.io.File(companion_bundle_dir).getCanonicalPath()))" newline ...
    "    error('Companion:INPUT_INVALID', 'Choose a reproduction output folder distinct from the source bundle.');" newline ...
    "end" newline ...
    "if isfolder(companion_output_dir)" newline ...
    "    companion_existing = dir(companion_output_dir);" newline ...
    "    if any(~ismember({companion_existing.name}, {'.', '..'}))" newline ...
    "        error('Companion:INPUT_INVALID', 'Choose a new or empty reproduction output folder to preserve existing files.');" newline ...
    "    end" newline ...
    "end" newline ...
    "companion_method = jsondecode(fileread(fullfile(companion_bundle_dir, 'method.json')));" newline ...
    "companion_request = companion_method.request;" newline ...
    "companion_request.output_dir = companion_output_dir;" newline ...
    "if exist('companion_cancel_path', 'var'), companion_request.cancel_path = companion_cancel_path; end" newline ...
    "if ~isempty(companion_request.input_path)" newline ...
    "    companion_request.input_path = fullfile(companion_bundle_dir, companion_request.input_path);" newline ...
    "end" newline ...
    "if strcmp(companion_request.operation, 'revise_figure')" newline ...
    "    companion_request.parameters.source_figure = fullfile(companion_bundle_dir, companion_request.parameters.source_figure);" newline ...
    "end" newline ...
    "companion_result = run_recipe(companion_request, companion_output_dir);" newline newline];
writeText(fullfile(outputDir, 'reproduce.m'), [char(join(header, '')) source]);
end

function result = isolatedRerun(scriptPath, outputDir, cancelPath)
companion_output_dir = outputDir; %#ok<NASGU>
companion_cancel_path = cancelPath; %#ok<NASGU>
run(scriptPath);
result = companion_result;
end

function verifyNative(outputDir, hasFigure)
matPath = fullfile(outputDir, 'analysis.mat');
saved = load(matPath);
required = {'input_data', 'results', 'parameters', 'details', 'figure_data'};
if ~all(isfield(saved, required)) || ~istable(saved.results)
    error('Companion:NATIVE_VERIFY_FAILED', 'The MAT artifact did not reopen with the expected editable data.');
end
if hasFigure
    f = openfig(fullfile(outputDir, 'figure.fig'), 'invisible');
    ownedFigure = onCleanup(@()close(f)); %#ok<NASGU>
    reopened = nativeFigureSignature(f);
    if ~isequaln(reopened, saved.figure_data)
        error('Companion:NATIVE_VERIFY_FAILED', 'The reopened figure changed curves, axes or labels.');
    end
    png = imread(fullfile(outputDir, 'figure.png'));
    if size(png,1) < 10 || size(png,2) < 10
        error('Companion:NATIVE_VERIFY_FAILED', 'The exported PNG has invalid dimensions.');
    end
    stream = fopen(fullfile(outputDir, 'figure.pdf'), 'rb');
    if stream < 0, error('Companion:NATIVE_VERIFY_FAILED', 'The exported PDF is unavailable.'); end
    streamGuard = onCleanup(@()fclose(stream)); %#ok<NASGU>
    signature = char(fread(stream, 5, '*char')');
    if ~strcmp(signature, '%PDF-')
        error('Companion:NATIVE_VERIFY_FAILED', 'The exported PDF header is invalid.');
    end
end
end

function compareNative(originalDir, reproducedDir)
original = load(fullfile(originalDir, 'analysis.mat'));
reproduced = load(fullfile(reproducedDir, 'analysis.mat'));
if ~isequaln(original, reproduced)
    error('Companion:NATIVE_VERIFY_FAILED', 'Reproduced MAT variable types, shapes or values differ.');
end
verifyNative(reproducedDir, isfile(fullfile(reproducedDir, 'figure.fig')));
end

function signature = nativeFigureSignature(f)
axesList = findall(f, 'Type', 'axes');
signature = cell(1, numel(axesList));
for idx = 1:numel(axesList)
    ax = axesList(idx);
    curves = findall(ax, 'Type', 'line');
    data = cell(1, numel(curves));
    for lineIdx = 1:numel(curves)
        line = curves(lineIdx);
        data{lineIdx} = struct('x', line.XData, 'y', line.YData, 'z', line.ZData, 'name', line.DisplayName);
    end
    signature{idx} = struct('title', ax.Title.String, 'x_label', ax.XLabel.String, ...
        'y_label', ax.YLabel.String, 'x_limits', ax.XLim, 'y_limits', ax.YLim, 'curves', {data});
end
end

function artifacts = artifactInventory(outputDir)
spec = {'input.csv', 'original_input', 'text/csv'; ...
    'input.tsv', 'original_input', 'text/tab-separated-values'; ...
    'source.fig', 'original_input', 'application/vnd.mathworks.matlab.fig'; ...
    'analysis.mat', 'native_data', 'application/x-matlab-data'; ...
    'results.csv', 'data_export', 'text/csv'; ...
    'figure.fig', 'native_figure', 'application/vnd.mathworks.matlab.fig'; ...
    'figure.png', 'preview', 'image/png'; ...
    'figure.pdf', 'figure_export', 'application/pdf'; ...
    'reproduce.m', 'script', 'text/x-matlab'; ...
    'method.json', 'method', 'application/json'};
artifacts = {};
for idx = 1:size(spec, 1)
    if isfile(fullfile(outputDir, spec{idx,1}))
        artifacts{end+1} = struct('name', spec{idx,1}, 'role', spec{idx,2}, 'media_type', spec{idx,3}); %#ok<AGROW>
    end
end
end

function writeJson(path, data)
writeText(path, jsonencode(data, 'ConvertInfAndNaN', true));
end

function writeText(path, text)
stream = fopen(path, 'w', 'n', 'UTF-8');
if stream < 0, error('Companion:NATIVE_EXECUTION_FAILED', 'An output file could not be opened for writing.'); end
streamGuard = onCleanup(@()fclose(stream)); %#ok<NASGU>
count = fprintf(stream, '%s', text);
if count < 0, error('Companion:NATIVE_EXECUTION_FAILED', 'An output file could not be written.'); end
end

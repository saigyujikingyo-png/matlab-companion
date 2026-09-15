function result = run_recipe(request, outputDir)
%RUN_RECIPE Fixed, base-MATLAB scientific recipes; no user code evaluation.
% This file is also inlined into each delivered reproduction script.
checkCancel(request);
if ~isfolder(outputDir)
    mkdir(outputDir);
end
p = request.parameters;
metrics = {};
f = [];
input_data = [];
figure_data = [];
switch request.operation
    case 'data_profile'
        input_data = readInput(request.input_path);
        columns = cell(1, width(input_data));
        for idx = 1:width(input_data)
            name = input_data.Properties.VariableNames{idx};
            values = input_data.(name);
            numeric = isnumeric(values) || islogical(values);
            low = NaN;
            high = NaN;
            if numeric
                finiteCount = sum(isfinite(values));
                missingCount = sum(isnan(values));
                nonfiniteCount = sum(isinf(values));
                if finiteCount > 0
                    low = min(values(isfinite(values)));
                    high = max(values(isfinite(values)));
                end
            else
                finiteCount = 0;
                missingCount = sum(ismissing(values));
                nonfiniteCount = 0;
            end
            columns{idx} = struct('name', name, 'numeric', logical(numeric), ...
                'finite_count', finiteCount, 'missing_count', missingCount, ...
                'nonfinite_count', nonfiniteCount, 'minimum', low, 'maximum', high);
        end
        details = struct('rows', height(input_data), 'columns', {columns});
        if isempty(columns)
            results = table();
        else
            results = struct2table([columns{:}]);
        end
        numerical = false;
        summary = 'CSV profile completed; no rows were removed or units inferred.';
        metrics{end+1} = metric('rows', height(input_data), '1', 'Imported CSV row count.');

    case {'plot_xy', 'linear_calibration'}
        input_data = readInput(request.input_path);
        x = numericColumn(input_data, p.x_column);
        y = numericColumn(input_data, p.y_column);
        if numel(x) < 2
            error('Companion:INPUT_INVALID', 'At least two finite paired rows are required.');
        end
        [f, ax] = createFigure();
        ownedFigure = onCleanup(@()closeOwned(f)); %#ok<NASGU>
        plot(ax, x, y, 'o', 'DisplayName', 'Input data', 'LineWidth', 1.2);
        grid(ax, 'on');
        xlabel(ax, unitLabel(p.x_column, p.x_unit), 'Interpreter', 'none');
        ylabel(ax, unitLabel(p.y_column, p.y_unit), 'Interpreter', 'none');
        title(ax, p.title, 'Interpreter', 'none');
        if strcmp(request.operation, 'plot_xy')
            results = table(x, y);
            details = struct('rows', numel(x), 'x_column', p.x_column, ...
                'y_column', p.y_column, 'x_unit', p.x_unit, 'y_unit', p.y_unit);
            summary = 'XY plot completed from every supplied row; units are user-declared.';
            numerical = isequal(x, input_data.(p.x_column)) && isequal(y, input_data.(p.y_column));
            metrics{end+1} = metric('rows', numel(x), '1', 'Number of paired values plotted.');
        else
            [details, results, metrics] = calibration(input_data, x, y, p);
            [sortedX, order] = sort(x);
            hold(ax, 'on');
            plot(ax, sortedX, results.fitted(order), '-', 'DisplayName', 'Linear calibration', 'LineWidth', 1.5);
            legend(ax, 'Location', 'best');
            summary = 'Linear calibration completed with explicit weighting, residuals and coefficient uncertainty.';
            numerical = verifyCalibration(results, details, p);
        end

    case 'first_order_kinetics'
        time = linspace(0, p.time_end, p.points)';
        relTol = 1e-9;
        absTol = max(1e-12, p.initial_concentration * 1e-12);
        options = odeset('RelTol', relTol, 'AbsTol', absTol, 'NonNegative', 1, ...
            'OutputFcn', @(t,y,flag)solverCancel(t,y,flag,request));
        solution = ode45(@(t,c)-p.rate_constant*c, [0, p.time_end], p.initial_concentration, options);
        checkCancel(request);
        if solution.x(end) ~= p.time_end
            error('Companion:NATIVE_VERIFY_FAILED', 'The solver did not complete the requested time domain.');
        end
        solvedTime = time;
        concentration = deval(solution, time)';
        analytical = p.initial_concentration * exp(-p.rate_constant * solvedTime);
        absolute_error = abs(concentration - analytical);
        maxError = max(absolute_error);
        if ~all(isfinite(concentration)) || any(concentration < 0) || maxError > 50*(absTol + relTol*p.initial_concentration)
            error('Companion:NATIVE_VERIFY_FAILED', 'The numerical trajectory did not agree with the analytical solution.');
        end
        results = table(solvedTime, concentration, analytical, absolute_error, ...
            'VariableNames', {'time', 'concentration', 'analytical', 'absolute_error'});
        details = struct('points', p.points, 'initial_concentration', p.initial_concentration, ...
            'rate_constant', p.rate_constant, 'time_end', p.time_end, ...
            'final_concentration', concentration(end), 'max_absolute_error', maxError, ...
            'relative_tolerance', relTol, 'absolute_tolerance', absTol, ...
            'concentration_unit', p.concentration_unit, 'time_unit', p.time_unit);
        [f, ax] = createFigure();
        ownedFigure = onCleanup(@()closeOwned(f)); %#ok<NASGU>
        plot(ax, solvedTime, concentration, '-', 'DisplayName', 'Simulated (ode45)', 'LineWidth', 1.5);
        hold(ax, 'on');
        plot(ax, solvedTime, analytical, '--', 'DisplayName', 'Analytical reference', 'LineWidth', 1.1);
        xlabel(ax, unitLabel('Time', p.time_unit), 'Interpreter', 'none');
        ylabel(ax, unitLabel('Concentration', p.concentration_unit), 'Interpreter', 'none');
        title(ax, p.title, 'Interpreter', 'none');
        legend(ax, 'Location', 'best');
        grid(ax, 'on');
        numerical = true;
        summary = 'First-order decay simulated by ode45 and checked against the analytical solution; no observations were invented.';
        metrics = {metric('final_concentration', concentration(end), p.concentration_unit, 'ode45 integration of dc/dt = -k*c.'), ...
            metric('max_absolute_error', maxError, p.concentration_unit, 'Maximum absolute difference from c0*exp(-k*t).')};

    case 'revise_figure'
        f = openfig(p.source_figure, 'invisible');
        ownedFigure = onCleanup(@()closeOwned(f)); %#ok<NASGU>
        before = figureSignature(f);
        axesList = findall(f, 'Type', 'axes');
        for idx = 1:numel(axesList)
            ax = axesList(idx);
            if ~isNullText(p.title), title(ax, p.title, 'Interpreter', 'none'); end
            if ~isNullText(p.x_label), xlabel(ax, p.x_label, 'Interpreter', 'none'); end
            if ~isNullText(p.y_label), ylabel(ax, p.y_label, 'Interpreter', 'none'); end
            if ~isempty(p.x_limits), xlim(ax, p.x_limits); end
            if ~isempty(p.y_limits), ylim(ax, p.y_limits); end
        end
        after = figureSignature(f);
        preserved = isequaln(curveValues(before), curveValues(after));
        if ~preserved
            error('Companion:NATIVE_VERIFY_FAILED', 'Figure revision changed scientific curve values.');
        end
        details = struct('title', parameterText(p.title), 'x_label', parameterText(p.x_label), ...
            'y_label', parameterText(p.y_label), 'curves_preserved', preserved);
        results = curvesTable(after);
        numerical = true;
        summary = 'Figure presentation revised while preserving all numeric curves.';

    otherwise
        error('Companion:INPUT_INVALID', 'The requested operation is not supported.');
end
checkCancel(request);
parameters = p;
if isfield(parameters, 'source_figure'), parameters.source_figure = 'source.fig'; end
if ~isempty(f)
    styleFigure(f);
    figure_data = figureSignature(f);
end
save(fullfile(outputDir, 'analysis.mat'), 'input_data', 'results', 'parameters', 'details', 'figure_data', '-v7');
reopened = load(fullfile(outputDir, 'analysis.mat'));
if ~isequaln(reopened.input_data, input_data) || ~isequaln(reopened.results, results) || ...
        ~isequaln(reopened.parameters, parameters) || ~isequaln(reopened.details, details) || ...
        ~isequaln(reopened.figure_data, figure_data)
    error('Companion:NATIVE_VERIFY_FAILED', 'MAT readback changed variable types, shapes or values.');
end
writetable(results, fullfile(outputDir, 'results.csv'));
checkCancel(request);
if ~isempty(f)
    savefig(f, fullfile(outputDir, 'figure.fig'));
    checkCancel(request);
    exportgraphics(f, fullfile(outputDir, 'figure.png'), 'Resolution', 160, 'BackgroundColor', 'white');
    checkCancel(request);
    exportgraphics(f, fullfile(outputDir, 'figure.pdf'), 'ContentType', 'vector', 'BackgroundColor', 'white');
end
checkCancel(request);
result = struct('details', details, 'metrics', {metrics}, 'summary', summary, ...
    'numerical', logical(numerical), 'has_figure', ~isempty(f));
end

function values = numericColumn(data, name)
if ~ismember(name, data.Properties.VariableNames)
    error('Companion:INPUT_INVALID', 'A selected column does not exist in the supplied CSV.');
end
values = data.(name);
if ~(isnumeric(values) || islogical(values)) || ~isvector(values) || ~isreal(values) || any(~isfinite(values))
    error('Companion:INPUT_INVALID', 'Selected columns must contain only finite real numbers; no rows are silently removed.');
end
values = double(values(:));
end

function data = readInput(inputPath)
if isempty(inputPath) || ~isfile(inputPath)
    error('Companion:INPUT_INVALID', 'The staged CSV input is unavailable.');
end
[~, ~, extension] = fileparts(inputPath);
switch lower(extension)
    case '.csv'
        delimiter = ',';
    case '.tsv'
        delimiter = sprintf('\t');
    otherwise
        error('Companion:INPUT_INVALID', 'Only staged CSV or TSV input is supported.');
end
data = readtable(inputPath, 'FileType', 'text', 'Delimiter', delimiter, ...
    'ReadVariableNames', true, 'VariableNamingRule', 'preserve', 'TextType', 'string');
if width(data) < 1
    error('Companion:INPUT_INVALID', 'The CSV contains no readable columns.');
end
if width(data) > 1000 || any(strlength(string(data.Properties.VariableNames)) > 200)
    error('Companion:INPUT_INVALID', 'CSV column count or column-name length exceeds the supported profile contract.');
end
end

function [details, results, metrics] = calibration(data, x, y, p)
n = numel(x);
weighted = ~isempty(p.weights_column);
weights = ones(n, 1);
if weighted
    suppliedWeights = numericColumn(data, p.weights_column);
    if any(suppliedWeights <= 0)
        error('Companion:INPUT_INVALID', 'Weights or known standard deviations must be strictly positive.');
    end
    if strcmp(p.weights_kind, 'known_sigma')
        weights = (1 ./ suppliedWeights).^2;
    else
        weights = suppliedWeights;
    end
elseif strcmp(p.weights_kind, 'known_sigma')
    error('Companion:INPUT_INVALID', 'Known-sigma weighting requires a column of measurement standard deviations.');
end
if any(~isfinite(weights)) || any(weights <= 0)
    error('Companion:INPUT_INVALID', 'The selected weights exceed the supported finite numerical range.');
end
if strcmp(p.intercept, 'free')
    design = [x, ones(n,1)];
elseif strcmp(p.intercept, 'zero')
    design = x;
else
    error('Companion:INPUT_INVALID', 'The intercept constraint must be free or zero.');
end
parameterCount = size(design, 2);
weightedDesign = design .* sqrt(weights);
weightedY = y .* sqrt(weights);
if any(~isfinite(weightedDesign), 'all') || any(~isfinite(weightedY)) || rank(weightedDesign) < parameterCount
    error('Companion:INPUT_INVALID', 'Calibration design is rank deficient or outside the finite numerical range.');
end
[q, r] = qr(weightedDesign, 0);
coefficients = r \ (q' * weightedY);
slope = coefficients(1);
intercept = 0;
if parameterCount == 2, intercept = coefficients(2); end
fitted = design * coefficients;
residual = y - fitted;
rss = sum(residual.^2);
wrss = sum(weights .* residual.^2);
dof = n - parameterCount;
if strcmp(p.intercept, 'zero')
    total = sum(weights .* y.^2);
    r2Method = 'Uncentered weighted R-squared for the origin-constrained model.';
else
    weightedMean = sum(weights .* y) / sum(weights);
    total = sum(weights .* (y - weightedMean).^2);
    r2Method = 'Centered weighted R-squared for the free-intercept model.';
end
if ~isfinite(total)
    error('Companion:INPUT_INVALID', 'Weighted sums exceeded the supported finite numerical range.');
end
rSquared = NaN;
if total > 0, rSquared = 1 - wrss/total; end
rSquaredReason = string(missing);
if isnan(rSquared), rSquaredReason = 'The chosen total sum of squares is zero.'; end
slopeSE = NaN;
interceptSE = NaN;
uncertaintyState = 'not_calculated';
uncertaintyReason = 'Residual-scaled uncertainty requires positive residual degrees of freedom.';
if strcmp(p.weights_kind, 'known_sigma') || dof > 0
    inverseR = r \ eye(parameterCount);
    covariance = inverseR * inverseR';
    if strcmp(p.weights_kind, 'relative')
        covariance = covariance * (wrss/dof);
        uncertaintyMethod = 'Standard errors from inverse weighted normal matrix scaled by weighted residual variance; x uncertainty is not modelled.';
    else
        uncertaintyMethod = 'Standard errors propagated from supplied independent known y standard deviations; no residual rescaling; x uncertainty is not modelled.';
    end
    standardErrors = sqrt(max(0, diag(covariance)));
    slopeSE = standardErrors(1);
    interceptSE = 0;
    if parameterCount == 2, interceptSE = standardErrors(2); end
    uncertaintyState = 'available';
    uncertaintyReason = '';
else
    uncertaintyMethod = 'Residual-scaled standard errors were not calculated.';
end
finiteValues = [slope, intercept, rss, wrss];
if any(~isfinite(finiteValues)) || (~isnan(rSquared) && ~isfinite(rSquared)) || ...
        (strcmp(uncertaintyState, 'available') && any(~isfinite([slopeSE, interceptSE])))
    error('Companion:INPUT_INVALID', 'The fit exceeded the supported finite numerical range.');
end
details = struct('rows', n, 'intercept_mode', p.intercept, 'weights_kind', p.weights_kind, ...
    'weighted', weighted, 'degrees_of_freedom', dof, 'slope', slope, 'intercept', intercept, ...
    'slope_standard_error', slopeSE, 'intercept_standard_error', interceptSE, ...
    'residual_sum_squares', rss, 'weighted_residual_sum_squares', wrss, 'r_squared', rSquared, 'r_squared_reason', rSquaredReason, ...
    'uncertainty_state', uncertaintyState, 'uncertainty_reason', nullableText(uncertaintyReason), ...
    'x_unit', p.x_unit, 'y_unit', p.y_unit);
effective_weight = weights;
results = table(x, y, fitted, residual, effective_weight);
slopeUnit = ['(' p.y_unit ')/(' p.x_unit ')'];
metrics = {metric('slope', slope, slopeUnit, 'Weighted least squares solved by QR decomposition.'), ...
    metric('intercept', intercept, p.y_unit, ['Intercept constraint: ' p.intercept '.']), ...
    metric('residual_sum_squares', rss, ['(' p.y_unit ')^2'], 'Unweighted sum of squared y residuals.'), ...
    metric('weighted_residual_sum_squares', wrss, wrssUnit(p), 'Sum of effective_weight * residual^2.'), ...
    metric('r_squared', rSquared, '1', r2Method), ...
    metric('slope_standard_error', slopeSE, slopeUnit, uncertaintyMethod), ...
    metric('intercept_standard_error', interceptSE, p.y_unit, uncertaintyMethod)};
if isnan(rSquared), metrics{5}.reason = 'The chosen total sum of squares is zero.'; end
if strcmp(uncertaintyState, 'not_calculated')
    metrics{6}.reason = uncertaintyReason;
    metrics{7}.reason = uncertaintyReason;
end
end

function ok = verifyCalibration(results, details, p)
x = results.x;
y = results.y;
prediction = details.slope*x + details.intercept;
scale = max(1, norm(y, Inf));
ok = max(abs(prediction-results.fitted)) <= 100*eps*scale && ...
    max(abs(y-prediction-results.residual)) <= 100*eps*scale;
normal = sum(results.effective_weight .* results.residual .* x);
normalScale = max(1, sum(abs(results.effective_weight .* y .* x)));
ok = ok && abs(normal) <= 1e-9*normalScale;
if strcmp(p.intercept, 'free')
    ok = ok && abs(sum(results.effective_weight .* results.residual)) <= ...
        1e-9*max(1, sum(abs(results.effective_weight .* y)));
end
if ~ok
    error('Companion:NATIVE_VERIFY_FAILED', 'Calibration residual and normal-equation checks failed.');
end
end

function unit = wrssUnit(p)
if strcmp(p.weights_kind, 'known_sigma'), unit = '1'; else, unit = ['(' p.y_unit ')^2']; end
end

function label = unitLabel(name, unit)
label = [char(name) ' (' char(unit) ')'];
end

function [f, ax] = createFigure()
f = figure('Visible', 'off', 'Color', 'w', 'InvertHardcopy', 'off');
palette = [0, 0.4470, 0.6980; 0.8353, 0.3686, 0; 0, 0.6196, 0.4510];
ax = axes(f, 'Color', 'w', 'XColor', 'k', 'YColor', 'k', 'ZColor', 'k', ...
    'ColorOrder', palette, 'GridColor', [0.65, 0.65, 0.65], 'NextPlot', 'add');
end

function styleFigure(f)
% Explicit export/native styling must not inherit the user's dark UI theme.
f.Color = 'w';
f.InvertHardcopy = 'off';
axesList = findall(f, 'Type', 'axes');
for idx = 1:numel(axesList)
    ax = axesList(idx);
    ax.Color = 'w';
    ax.XColor = 'k';
    ax.YColor = 'k';
    ax.ZColor = 'k';
    ax.GridColor = [0.65, 0.65, 0.65];
    ax.Title.Color = 'k';
    ax.XLabel.Color = 'k';
    ax.YLabel.Color = 'k';
    ax.ZLabel.Color = 'k';
end
legends = findall(f, 'Type', 'legend');
for idx = 1:numel(legends)
    legends(idx).Color = 'w';
    legends(idx).TextColor = 'k';
    legends(idx).EdgeColor = [0.65, 0.65, 0.65];
end
end

function item = metric(name, value, unit, method)
state = 'available';
reason = string(missing);
if ~isfinite(value)
    state = 'not_calculated';
    value = NaN;
    reason = 'The quantity is undefined for this input or was not calculated.';
end
item = struct('name', name, 'value', value, 'unit', unit, 'state', state, 'method', method, 'reason', reason);
end

function value = nullableText(value)
if isempty(value), value = string(missing); end
end

function yes = isNullText(value)
yes = isnumeric(value) && isempty(value);
end

function value = parameterText(value)
if isNullText(value), value = string(missing); end
end

function signature = figureSignature(f)
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

function values = curveValues(signature)
values = cell(1, numel(signature));
for idx = 1:numel(signature), values{idx} = signature{idx}.curves; end
end

function results = curvesTable(signature)
axes_index = [];
curve_index = [];
point_index = [];
x = [];
y = [];
for ai = 1:numel(signature)
    curves = signature{ai}.curves;
    for ci = 1:numel(curves)
        count = numel(curves{ci}.x);
        axes_index = [axes_index; repmat(ai,count,1)]; %#ok<AGROW>
        curve_index = [curve_index; repmat(ci,count,1)]; %#ok<AGROW>
        point_index = [point_index; (1:count)']; %#ok<AGROW>
        x = [x; curves{ci}.x(:)]; %#ok<AGROW>
        y = [y; curves{ci}.y(:)]; %#ok<AGROW>
    end
end
results = table(axes_index, curve_index, point_index, x, y);
end

function stop = solverCancel(~, ~, ~, request)
stop = ~isempty(request.cancel_path) && isfile(request.cancel_path);
end

function checkCancel(request)
if ~isempty(request.cancel_path) && isfile(request.cancel_path)
    error('Companion:CANCELLED', 'Cancellation observed at a safe recipe boundary.');
end
end

function closeOwned(f)
if ~isempty(f) && isgraphics(f), close(f); end
end
